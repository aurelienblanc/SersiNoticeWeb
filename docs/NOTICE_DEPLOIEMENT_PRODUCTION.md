# SERSI Notices
## Notice de déploiement en production

Version 1.1 - 22 octobre 2026. Utiliser une révision validée de `main` et consigner son SHA lors de l’installation.

Cette notice s'adresse à la personne chargée du serveur et du réseau. Elle décrit une installation sur une VM Ubuntu 24.04 LTS, avec Docker Engine, PostgreSQL et HTTPS. Le service est déployé sur le réseau interne à `https://sersi-notices.sersi.fr/`. Pour une nouvelle installation, choisir le matériel, l’adresse IP et l’autorité de certification avec votre prestataire informatique. Les valeurs données ci-dessous sont des exemples à remplacer.

Le catalogue est ouvert aux collaborateurs joignant le réseau interne ou le VPN. L'administration utilise un seul mot de passe commun. L’environnement de développement reste indépendant du serveur de production.

**Sources de référence :** cette notice et le dossier `deploy/production/` du dépôt, contenant `compose.production.yaml`, `nginx.https.conf` et `env.production.example`. Les commandes sont à copier depuis la version Markdown. Les exemples HTTPS ne sont pas activés par le simple ajout de la documentation au dépôt.

### Parcours conseillé

1. Valider la fiche d'installation et préparer la VM.
2. Installer Docker, récupérer la révision et préparer les fichiers de production.
3. Configurer le DNS, le certificat, les secrets et les accès réseau.
4. Démarrer les services et reprendre une sauvegarde du catalogue actuel.
5. Effectuer la recette, une sauvegarde et un essai de restauration isolé.
6. Organiser la surveillance et les mises à jour avant l'ouverture générale.

## 1. Fiche d'installation à compléter

| Élément | Exemple ou choix proposé | Valeur de production |
| --- | --- | --- |
| Hébergement | VM Linux dédiée, allumée en permanence | À renseigner |
| Système | Ubuntu Server 24.04 LTS, 64 bits | À renseigner |
| Ressources de départ | 2 vCPU, 4 Go de RAM, 80 Go de disque | À confirmer |
| Adresse privée fixe | 192.168.50.20 | À renseigner |
| Nom DNS interne | notices.entreprise.example | À remplacer |
| URL des collaborateurs | https://notices.entreprise.example | À remplacer |
| Réseaux autorisés | Sous-réseaux LAN de la société et du VPN | À renseigner |
| Administration serveur | Compte SSH nominatif avec sudo | À renseigner |
| Certificat HTTPS | Certificat accepté par les postes et couvrant le nom DNS | À fournir |
| Copie hors serveur | NAS, dépôt de sauvegarde ou outil de sauvegarde d'entreprise | À renseigner |
| Responsable d'exploitation | Maintenance, incidents et renouvellement du certificat | À désigner |
| Perte de données / délai de reprise | Objectifs à fixer et à tester | À renseigner |

Le dimensionnement est une estimation de départ, pas un minimum garanti par un éditeur. Il doit être ajusté après des essais représentatifs d'exports simultanés et de restauration. Le catalogue contrôlé pendant la préparation comptait 369 produits, dont 365 actifs, et 851 fichiers pour environ 631 Mio de sauvegarde ZIP. Les valeurs exactes à la bascule doivent être relevées sur la source.

Le disque héberge les images Docker, PostgreSQL, les documents, les fichiers temporaires et les copies de sécurité. Les sauvegardes manuelles et les anciens fichiers remplacés peuvent s'accumuler : conserver une marge, surveiller l'espace et définir une politique d'archivage. Une copie située sur le même serveur ne couvre pas la perte de ce serveur.

## 2. Architecture et stockage

Les navigateurs utilisent HTTPS sur le port 443. Nginx termine le chiffrement et transmet les requêtes à Django/Gunicorn dans le réseau Docker. Le service de maintenance traite les sauvegardes et restaurations en arrière-plan. PostgreSQL conserve les données structurées.

```text
Collaborateurs LAN ou VPN
          |
  Pare-feu / règles réseau
          |
   Nginx HTTPS :443
          |
 Django / Gunicorn :8000 --- PostgreSQL :5432
          |                       |
 Documents /data          Volume database
          |
 Maintenance --- Archives /backups --- Copie hors serveur
```

| Service | Rôle | Exposition sur le serveur |
| --- | --- | --- |
| proxy | HTTPS et redirection HTTP vers HTTPS | IP privée :80 et :443 |
| web | Application, administration, téléchargements | Aucune publication de :8000 |
| maintenance | Sauvegardes, vérifications, restaurations, rétention | Aucun port publié |
| db | PostgreSQL 17 | Aucune publication de :5432 |

Le profil décrit ici conserve le nom de projet Compose `sersi-notice-web`. Les volumes principaux sont `sersi-notice-web_database` et `sersi-notice-web_documents`. Les archives utilisent le dossier hôte `/srv/sersi-notices/archives`, monté dans les conteneurs sur `/backups`. Sans ce réglage, la configuration de base emploie le volume nommé `archives`.

Le code est dans `/srv/sersi-notices/app`. Les configurations HTTPS et certificats sont dans `/srv/sersi-notices/config`, séparés du code pour être conservés lors des mises à jour. PostgreSQL et les documents restent sur le stockage local Linux de la VM. Le NAS peut recevoir les copies de sauvegarde ; les conditions de montage et de disponibilité sont à valider avec l'informatique.

**Point de contrôle :** l'accès au réseau donne accès au catalogue et aux documents. Le mot de passe commun protège l'administration, pas la consultation des fichiers. Le nom d'hôte autorisé dans Django ne filtre pas les réseaux clients.

## 3. Préparer le serveur et Docker

### 3.1. Préparation de la VM

Prévoir une VM dédiée, une IP privée stable, une résolution DNS disponible depuis le LAN et le VPN, et une horloge synchronisée. Les téléchargements initiaux nécessitent un accès aux dépôts Ubuntu, Docker, GitHub et Python, ou à leurs miroirs internes. Les navigateurs des salariés n'ont pas besoin d'un accès Internet pour utiliser l'application.

Les commandes Linux de cette notice sont destinées à **Bash**, sur le serveur. Ouvrir une session avec le compte d'administration puis utiliser `sudo -i`. Les commandes Docker donnent des privilèges importants sur l'hôte ; limiter cet accès aux administrateurs. Voir [Docker - post-installation Linux](https://docs.docker.com/engine/install/linux-postinstall/).

```bash
sudo -i
apt update
apt install -y ca-certificates curl git python3 openssl
timedatectl status
```

### 3.2. Installer Docker Engine

Sur une VM Ubuntu 24.04 neuve, installer Docker depuis son dépôt APT officiel. La procédure suivante utilise la distribution `noble`. Pour un autre système ou une machine déjà équipée de conteneurs, suivre la procédure correspondante de [Docker - installation Ubuntu](https://docs.docker.com/engine/install/ubuntu/) avant de poursuivre.

```bash
install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
chmod 0644 /etc/apt/keyrings/docker.asc

printf '%s\n' \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu noble stable" \
  > /etc/apt/sources.list.d/docker.list

apt update
apt install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
docker version
docker compose version
docker run --rm hello-world
```

Le programme attendu est le plugin `docker compose`, avec les options `--wait` et `--wait-timeout`. Le lancement applicatif utilisera Gunicorn et Nginx. Le serveur `manage.py runserver` reste réservé aux essais, conformément à la [checklist de déploiement Django](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/).

## 4. Installer le code et les fichiers de production

### 4.1. Récupérer une révision précise

Le dépôt web est `aurelienblanc/SersiNoticeWeb`. L'accès au dépôt privé doit être autorisé sur le serveur, par exemple avec une clé de déploiement GitHub en lecture seule. Conserver la clé privée sur le serveur et contrôler l'identité de l'hôte SSH avant sa première acceptation. Voir [GitHub - clés de déploiement](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys).

Les versions livrées sont fusionnées dans `main`. Choisir un SHA dont les contrôles sont réussis, le renseigner ci-dessous et conserver cette référence. Les mises à jour ultérieures suivent le chapitre 12.

```bash
install -d -m 0750 /srv/sersi-notices
install -d -m 0750 /srv/sersi-notices/config
install -d -m 0700 /srv/sersi-notices/config/tls
install -d -m 0700 /srv/sersi-notices/recovery
install -d -m 0770 -o 10001 -g 10001 /srv/sersi-notices/archives

git clone git@github.com:aurelienblanc/SersiNoticeWeb.git \
  /srv/sersi-notices/app
cd /srv/sersi-notices/app
SN_REVISION=SHA_VALIDE_A_RENSEIGNER
git cat-file -e "${SN_REVISION}^{commit}"
git checkout --detach "$SN_REVISION"
git rev-parse HEAD
```

### 4.2. Préparer les fichiers de production

Les exemples sont fournis dans la révision du dépôt choisie. Copier ces fichiers hors du code pour conserver la configuration locale lors des mises à jour. Ces commandes concernent une installation neuve ; ne pas remplacer un `.env` de production existant.

```bash
cd /srv/sersi-notices/app
install -m 0644 deploy/production/compose.production.yaml \
  /srv/sersi-notices/config/compose.production.yaml
install -m 0644 deploy/production/nginx.https.conf \
  /srv/sersi-notices/config/nginx.https.conf
install -m 0600 deploy/production/env.production.example .env
```

Les fichiers de production surchargent la configuration de base sans la modifier : ils ajoutent HTTPS, les montages des certificats et la rotation des logs Docker. Ce principe de surcharge est décrit dans [Docker Compose - production](https://docs.docker.com/compose/how-tos/production/).

## 5. Configurer les paramètres et les secrets

### 5.1. Générer les secrets et renseigner les adresses

Dans le bloc suivant, **remplacer le nom et l'IP avant exécution**. Le domaine `.example` est fictif. Les deux secrets sont générés directement dans le fichier, sans être affichés dans le terminal.

```bash
cd /srv/sersi-notices/app
export SN_HOST=notices.entreprise.example
export SN_IP=192.168.50.20

python3 <<'PY'
import os, re, secrets
from pathlib import Path
p = Path('.env')
text = p.read_text()
values = {
    'SERSI_SECRET_KEY': secrets.token_urlsafe(64),
    'POSTGRES_PASSWORD': secrets.token_urlsafe(48),
    'SERSI_BIND_ADDRESS': os.environ['SN_IP'],
    'SERSI_ALLOWED_HOSTS': os.environ['SN_HOST'],
    'SERSI_TRUSTED_ORIGINS': 'https://' + os.environ['SN_HOST'],
}
for key, value in values.items():
    text = re.sub(r'^' + key + r'=.*$', key + '=' + value,
                  text, flags=re.MULTILINE)
p.write_text(text)
p.chmod(0o600)
PY

sed -i "s/notices\.entreprise\.example/${SN_HOST}/g" \
  /srv/sersi-notices/config/nginx.https.conf
```

**Ce bloc est réservé à l'installation initiale.** Pour modifier un hôte sur une installation existante, éditer les seules lignes concernées. La rotation des secrets est décrite au chapitre 13 ; remplacer le mot de passe PostgreSQL uniquement dans `.env` ne change pas celui d'une base déjà initialisée.

### 5.2. Comprendre les variables

| Variable | Valeur attendue / rôle |
| --- | --- |
| SERSI_SECRET_KEY | Secret Django propre à la production ; conserver dans le coffre de l'entreprise |
| POSTGRES_PASSWORD | Secret PostgreSQL distinct du mot de passe commun et de la clé Django |
| SERSI_BIND_ADDRESS | IP privée réellement affectée au serveur |
| SERSI_PORT | 80, pour la redirection HTTP du profil fourni |
| SERSI_HTTPS_PORT | 443, port HTTPS normal pour les utilisateurs |
| SERSI_ALLOWED_HOSTS | Nom DNS exact, sans protocole, chemin ni port ; virgules si plusieurs noms |
| SERSI_TRUSTED_ORIGINS | URL complète HTTPS, avec port si le port n'est pas standard |
| SERSI_HTTPS | 1 avec le profil HTTPS et son certificat opérationnels |
| SERSI_BACKUP_STORAGE | /srv/sersi-notices/archives, ou dossier de stockage validé |
| SERSI_PRODUCTION_CONFIG_DIR | /srv/sersi-notices/config |
| COMPOSE_PROJECT_NAME | sersi-notice-web ; conserver ce nom pour retrouver les mêmes volumes |
| COMPOSE_FILE | Chemins absolus vers compose.yaml puis compose.production.yaml, séparés par : sur Linux |

Le fichier `.env` pilote aussi la sélection des deux fichiers Compose ; exécuter toutes les commandes depuis `/srv/sersi-notices/app`. Voir [Docker - variables Compose](https://docs.docker.com/compose/how-tos/environment-variables/envvars/). `SERSI_DEBUG=0` est fixé dans les services de production de la configuration de base.

Protéger `.env` et la clé TLS en lecture aux seuls administrateurs. Leur copie de reprise doit être sauvegardée dans un stockage chiffré et contrôlé. Le fichier `.env` ne fait pas partie des sauvegardes ZIP applicatives. La commande `docker compose config --quiet` valide la configuration sans afficher les secrets résolus.

## 6. DNS, certificat HTTPS et restriction réseau

### 6.1. Nom et certificat

Créer un enregistrement DNS interne reliant le nom choisi à l'IP privée. Le VPN doit fournir la même résolution et les routes vers le serveur. Faire fournir par l'informatique un certificat couvrant ce nom dans ses SAN, sa chaîne et sa clé privée, puis installer :

```text
/srv/sersi-notices/config/tls/notices.crt
/srv/sersi-notices/config/tls/notices.key
```

`notices.crt` contient le certificat serveur et, si nécessaire, les intermédiaires. La clé doit correspondre au certificat. Avec une autorité interne, déployer sa confiance sur les postes et navigateurs avant la recette. Le fichier Nginx fourni active TLS 1.2 et TLS 1.3. Voir [Nginx - configuration TLS](https://nginx.org/en/docs/http/ngx_http_ssl_module.html).

```bash
chmod 0600 /srv/sersi-notices/config/tls/notices.key
chmod 0644 /srv/sersi-notices/config/tls/notices.crt
openssl x509 -in /srv/sersi-notices/config/tls/notices.crt \
  -noout -subject -issuer -dates -ext subjectAltName
```

Les permissions des dossiers et fichiers doivent permettre au processus principal Nginx de lire le certificat dans le montage en lecture seule. Les sauvegardes, elles, doivent être inscriptibles par l'UID/GID numérique **10001:10001** employé par l'application. Sur un NAS, contrôler aussi les permissions côté partage et la présence effective du montage.

### 6.2. Règles réseau

Faire appliquer puis vérifier les règles suivantes sur le pare-feu réseau et/ou celui de l'hyperviseur. La règle de refus doit couvrir aussi les réseaux invités et les autres interfaces du serveur.

| Source | Destination | Autorisation |
| --- | --- | --- |
| LAN de l'entreprise et VPN autorisé | IP privée du serveur :443 | Autoriser |
| LAN de l'entreprise et VPN autorisé | IP privée du serveur :80 | Autoriser la redirection HTTPS |
| Réseau d'administration | SSH du serveur | Selon la politique informatique |
| Autres sources / Internet | Ports applicatifs du serveur | Refuser, sans redirection NAT Internet |
| Postes utilisateurs | Serveur :5432 et :8000 | Aucune publication ni règle d'ouverture |

**Particularité Docker :** les ports publiés peuvent contourner les règles UFW ordinaires. Une règle UFW seule ne démontre donc pas la restriction LAN/VPN. Utiliser un filtrage compatible avec le backend Docker ou un pare-feu réseau, puis tester depuis une source autorisée et une source refusée. Voir [Docker - ports et pare-feu](https://docs.docker.com/engine/network/packet-filtering-firewalls/).

### 6.3. Si l'entreprise possède déjà un reverse proxy HTTPS

La procédure principale termine HTTPS dans le Nginx fourni. Avec un proxy d'entreprise terminant le TLS en amont, faire adapter le chemin par l'informatique : conserver le nom d'hôte et transmettre le protocole HTTPS de façon fiable. Le Nginx HTTP de base écrit `X-Forwarded-Proto` à partir de son propre `$scheme` ; il verrait alors HTTP et provoquerait des redirections répétées si `SERSI_HTTPS=1`.

Une configuration adaptée peut fixer `X-Forwarded-Proto https` sur le seul accès backend réservé au proxy d'entreprise. Ce backend doit être joignable uniquement par ce proxy. La transmission aveugle d'un en-tête fourni par le client n'est pas une preuve de HTTPS. Voir [Nginx - en-têtes du proxy](https://nginx.org/en/docs/http/ngx_http_proxy_module.html). Ce scénario doit faire l'objet d'une validation réseau séparée ; la configuration fournie correspond au TLS terminé dans son Nginx.

## 7. Démarrer l'application et créer l'accès administrateur

Les fichiers `.env`, les configurations copiées, le DNS et les deux fichiers TLS doivent être prêts. Sur le serveur :

```bash
cd /srv/sersi-notices/app
docker compose config --quiet
docker compose up -d --build --wait --wait-timeout 300
docker compose ps
docker compose exec proxy nginx -t
docker compose exec web python manage.py check --deploy
docker compose exec maintenance python manage.py maintenance_worker --check-health
docker compose exec web python manage.py set_admin_password
```

Attendre que `db`, `web` et `maintenance` soient sains et que `proxy` soit démarré. La construction peut être plus longue au premier lancement. Les migrations s'exécutent automatiquement au démarrage du service web. Les ressources CSS et images sont préparées dans l'image. Le contrôle `nginx -t` doit annoncer que la syntaxe et le test de configuration réussissent.

La dernière commande demande un mot de passe commun et sa confirmation. La validation actuelle impose au moins 12 caractères et refuse les mots de passe trop simples. Le saisir au clavier ; aucun mot de passe de production n'est fourni dans cette notice. Le mot de passe du poste de test n'est pas contenu dans la sauvegarde portable. Il n'est pas nécessaire de créer un superutilisateur Django.

`check --deploy` doit être examiné avant ouverture. Les réglages HSTS `includeSubDomains` et `preload` peuvent encore produire des avertissements : leur activation concerne le domaine et ses sous-domaines et doit être décidée avec l'informatique. DEBUG, hôtes autorisés, secret et cookies sécurisés doivent correspondre à la production.

Depuis un poste autorisé et avec la chaîne de confiance installée :

```bash
curl --fail --show-error https://notices.entreprise.example/health/
```

Remplacer le nom dans cette commande. Réponse attendue : HTTP 200 et `ok`. Une vérification avec une chaîne interne peut employer `--cacert /chemin/autorite.pem`. Garder la vérification du certificat active. Ouvrir ensuite l'URL du site et `/admin/` dans le navigateur.

## 8. Reprendre le catalogue actuel

### 8.1. Sur le poste de test

1. Prévoir une période de bascule et arrêter les modifications du catalogue source pendant le transfert.
2. Dans l'administration du poste de test, ouvrir **Sauvegardes et restauration**.
3. Créer une sauvegarde fraîche, attendre l'état **Terminée**, puis vérifier la présence de l'état **Vérifiée**.
4. Télécharger l'archive et relever sa date, sa taille et ses compteurs de produits et fichiers. Conserver cette copie jusqu'à la recette complète de production.

Le ZIP contient le catalogue, les relations, les fichiers référencés, les historiques et un manifeste d'intégrité. Il permet de passer de SQLite au PostgreSQL du serveur. Il ne contient pas le mot de passe, les sessions, les réglages de maintenance, les certificats, `.env` ni les autres archives.

### 8.2. Sur le serveur neuf

1. Se connecter à `https://NOM-CHOISI/admin/` avec le mot de passe défini sur la cible.
2. Ouvrir **Sauvegardes et restauration**, choisir le ZIP dans **Importer une sauvegarde**, puis lancer **Importer et vérifier**.
3. Attendre la fin de la vérification. Un import seul ne remplace pas le catalogue.
4. Choisir **Restaurer**, saisir le mot de passe de la cible et la confirmation `RESTAURER`.
5. Attendre l'opération terminée. Une sauvegarde de protection est créée avant le remplacement ; sur un serveur neuf elle contient le catalogue encore vide.
6. Comparer les compteurs, tester les documents et les exports, puis régler la planification de sauvegarde sur cette cible.

Pendant la restauration, le catalogue est temporairement indisponible ; la page de suivi reste utilisable. Le mot de passe courant de la cible est conservé. L'import ne rétablit pas l'horaire et les durées de conservation du poste source : les contrôler dans la nouvelle administration.

Une vérification complémentaire peut être effectuée sur le serveur :

```bash
docker compose exec -T web python manage.py shell <<'PY'
from catalogue.models import Produit, Document
print('Produits total :', Produit.objects.count())
print('Produits actifs :', Produit.objects.filter(actif=True).count())
print('Documents :', Document.objects.count())
print('Fichiers disponibles :', sum(d.disponible for d in Document.objects.all()))
PY
```

## 9. Recette avant ouverture générale

Consigner le résultat, la date et l'opérateur pour chaque point. Effectuer la recette depuis un poste LAN et un poste connecté au VPN.

| Contrôle | Résultat attendu |
| --- | --- |
| DNS et certificat | Bon nom, certificat accepté, aucune alerte HTTPS |
| Réseau | Accès LAN/VPN réussi, accès depuis un réseau refusé effectivement bloqué |
| Catalogue | Produits actifs, marques et documents cohérents avec la source |
| Recherche et filtres | Recherche par référence/nom, systèmes, marque et catégorie utilisables |
| Présentation | Référence en gras au-dessus du nom ; affichage PC et mobile lisible |
| PDF individuel | Téléchargement d'un document réel et ouverture correcte |
| Dossier ZIP | Récapitulatif correct, sous-dossiers directement à la racine, sans LISEZ-MOI |
| Expirations / manquants | Avertissements visibles et confirmation d'export incomplet si nécessaire |
| Administration | Mot de passe commun valide ; ouverture anonyme redirigée vers la connexion |
| Dépôt d'un fichier | Essai sur une donnée de recette, puis contrôle du téléchargement |
| Maintenance | Service actif, sauvegarde manuelle terminée et vérifiée |
| Journal | Opérations de recette visibles ; export CSV utilisable |
| Reprise | Restauration d'un ZIP sur une installation isolée, puis contrôle des PDF |
| Redémarrage | Après redémarrage maîtrisé de la VM : services, catalogue et maintenance revenus |

La préparation a validé 49 tests sous SQLite et PostgreSQL, un essai Compose et une restauration isolée des 851 fichiers du jeu de travail. Ces résultats ne remplacent pas la recette du futur serveur, de son certificat, du NAS et du filtrage réseau. La sauvegarde automatisée du premier jour doit aussi être contrôlée avant de considérer l'exploitation comme stabilisée.

## 10. Sauvegardes, logs et surveillance

### 10.1. Régler les sauvegardes applicatives

Dans **Sauvegardes et restauration**, les valeurs initiales sont : sauvegarde quotidienne à **02:00, heure de Paris**, conservation des **7 dernières sauvegardes automatiques** et **90 jours de journaux**. Les copies manuelles et importées restent conservées jusqu'à suppression explicite. Les trois dernières sauvegardes de protection avant restauration suivent une conservation séparée.

Vérifier ces valeurs sur le serveur cible. Avec une sauvegarde par jour, une perte peut concerner jusqu'à environ une journée de changements, davantage si les opérations échouent : fixer l'objectif avec le responsable. Le service `maintenance` et le serveur doivent rester actifs. Un arrêt du service peut être rattrapé au redémarrage pour une journée manquée ; l'état de la dernière opération doit rester surveillé.

Planifier une copie hors serveur après les sauvegardes réussies. Le transfert et sa rétention relèvent de l'outil de sauvegarde de l'entreprise : l'application ne synchronise pas automatiquement les archives vers un NAS distant. Tester la lisibilité de la copie et une restauration isolée régulièrement.

Une sauvegarde manuelle depuis le serveur peut être créée et copiée sur l'hôte :

```bash
cd /srv/sersi-notices/app
sh deploy/backup.sh /srv/sersi-notices/recovery/exports-manuels
```

Ce script respecte le `.env` et ses fichiers Compose lorsqu'il est lancé depuis ce dossier. Il crée aussi une archive applicative dans le stockage des sauvegardes. Les copies du dossier `exports-manuels` ne font pas l'objet d'une purge automatique par l'application.

### 10.2. Journaux et contrôles réguliers

Le journal de l'administration trace le catalogue, les exports, les accès et la maintenance. Avec un mot de passe partagé, il ne permet pas d'attribuer une opération à une personne. Les corps des requêtes et mots de passe ne sont pas enregistrés dans ce journal applicatif.

```bash
cd /srv/sersi-notices/app
docker compose ps
docker compose logs --since 24h --tail 200 web maintenance proxy
docker compose exec maintenance python manage.py maintenance_worker --check-health
df -h
docker system df
```

Le profil fourni applique le pilote Docker `local`, avec rotation à 10 Mo et 5 fichiers par conteneur. Ces journaux techniques sont distincts des 90 jours du journal applicatif et peuvent contenir des IP et chemins HTTP. Les consulter avec `docker compose logs`. Voir [Docker - pilote de logs local](https://docs.docker.com/engine/logging/drivers/local/).

| Fréquence proposée | Vérification / action |
| --- | --- |
| Chaque jour ouvré | Services, dernier backup terminé, copie hors serveur, espace disponible |
| Chaque semaine | Erreurs du journal, accumulation de copies manuelles et de fichiers, mises à jour à planifier |
| Chaque mois | Test de restauration isolé et ouverture de plusieurs PDF restaurés |
| Avant chaque mise à jour | Backup applicatif et instantané de reprise cohérent, version et image conservées |
| Avant l'expiration TLS | Renouvellement du certificat et recette LAN/VPN |
| Après changement réseau / VPN | DNS, certificat et test d'une source autorisée et d'une source refusée |

## 11. Instantané complet avant une mise à jour

Le ZIP applicatif restaure le métier. Pour revenir exactement à une ancienne version après une migration de schéma, conserver aussi PostgreSQL, les documents physiques, les archives, la configuration et l'image de cette version. La méthode ci-dessous prévoit une interruption pendant la copie et utilise PostgreSQL 17. Voir [PostgreSQL - sauvegardes logiques](https://www.postgresql.org/docs/17/backup-dump.html).

Avant de commencer, attendre que les opérations de maintenance soient terminées et prévoir assez d'espace pour une copie complète. Exécuter ce bloc dans Bash avec arrêt sur erreur. Si une commande échoue, laisser le site fermé le temps de diagnostiquer ; ne pas considérer l'instantané partiel comme une sauvegarde valide.

```bash
set -euo pipefail
cd /srv/sersi-notices/app
SN_RECOVERY=/srv/sersi-notices/recovery/$(date +%Y%m%d-%H%M%S)
install -d -m 0700 "$SN_RECOVERY"
umask 077

docker compose stop proxy maintenance
sh deploy/backup.sh "$SN_RECOVERY"
docker compose stop web

docker compose exec -T db pg_dump -U sersi -d sersi -Fc \
  > "$SN_RECOVERY/database.dump"
docker compose run --rm --no-deps -T web python -c \
  'import sys,tarfile; t=tarfile.open(fileobj=sys.stdout.buffer,mode="w|gz"); t.add("/data",arcname="."); t.close()' \
  > "$SN_RECOVERY/documents.tar.gz"

cp -a .env "$SN_RECOVERY/env.production"
cp -a /srv/sersi-notices/config "$SN_RECOVERY/config"
cp -a /srv/sersi-notices/archives "$SN_RECOVERY/archives"
git rev-parse HEAD > "$SN_RECOVERY/revision.txt"
docker compose images > "$SN_RECOVERY/images.txt"
docker image save sersi-notice-web:local \
  --output "$SN_RECOVERY/application-image.tar"

test -s "$SN_RECOVERY/database.dump"
test -s "$SN_RECOVERY/documents.tar.gz"
test -s "$SN_RECOVERY/application-image.tar"
docker compose up -d --wait --wait-timeout 300
```

Conserver ce dossier complet, les références des images PostgreSQL/Nginx et une copie chiffrée hors serveur. L'instantané contient des secrets et des clés privées. Sa rétention doit être gérée séparément de celle des ZIP applicatifs. Si le NAS a été monté à un autre endroit, adapter la source `archives` à la valeur réelle de `SERSI_BACKUP_STORAGE`.

## 12. Mettre à jour et revenir en arrière

### 12.1. Mettre à jour l'application

1. Choisir une révision passée en recette et dont les contrôles sont réussis. Prévoir une fenêtre d'interruption et consulter les changements de migrations.
2. Réaliser l'instantané complet du chapitre 11 et vérifier sa présence hors serveur.
3. Attendre de nouveau la fin des opérations, fermer le proxy, arrêter le service de maintenance puis le service web.
4. Récupérer le code et placer le dépôt sur la révision choisie. Les fichiers `.env` et `config/` de production sont conservés.

```bash
cd /srv/sersi-notices/app
git status --short
git fetch origin

# Remplacer le texte ci-dessous par le SHA validé de la version cible.
SN_NOUVELLE_REVISION=SHA_VALIDE_A_RENSEIGNER
git cat-file -e "${SN_NOUVELLE_REVISION}^{commit}"
docker compose stop proxy maintenance web
git checkout --detach "$SN_NOUVELLE_REVISION"

docker compose build web
docker compose up -d --wait --wait-timeout 300 db web maintenance
docker compose up -d --force-recreate --no-deps proxy
docker compose exec proxy nginx -t
docker compose exec web python manage.py check --deploy
docker compose exec maintenance python manage.py maintenance_worker --check-health
```

Le redémarrage du web applique les migrations. La migration `catalogue.0005_remove_document_source_path` retire une métadonnée de chemin source, sans supprimer les documents, les relations ni les PDF. Les nouvelles sauvegardes utilisent le format web 2 ; les sauvegardes web de format 1 restent lisibles. Une ancienne version de l’application ne lit pas le format 2 : conserver l’instantané complet avant mise à jour pour un retour arrière. Le proxy est recréé pour reprendre la configuration et résoudre de nouveau l'adresse Docker du service web. Vérifier ensuite HTTPS, la connexion, un PDF et un ZIP, puis une sauvegarde. Garder l'ancienne image et l'instantané jusqu'à stabilisation.

La ligne `git status --short` doit être examinée : une modification locale de fichier suivi doit être traitée avant le changement de version. Les mises à jour de Docker Engine, de PostgreSQL et des images de base sont à planifier et tester séparément. Le passage à une nouvelle version majeure PostgreSQL nécessite une procédure dédiée ; modifier uniquement le numéro d'image n'effectue pas la migration.

### 12.2. Retour arrière

Un retour du code seul ne revient pas sur les changements de schéma déjà appliqués. Si la compatibilité n'est pas démontrée, conserver le site fermé et restaurer l'instantané complet dans une installation de reprise, avec le code et l'image correspondants. La procédure du chapitre 14 rétablit cette cohérence. Après validation, basculer DNS ou IP vers l'installation restaurée.

## 13. Administration courante et secrets

### 13.1. Réinitialiser le mot de passe commun

```bash
cd /srv/sersi-notices/app
docker compose exec web python manage.py set_admin_password
```

La commande demande le nouveau mot de passe deux fois et invalide les sessions administrateur existantes. Le lien **Mot de passe commun** dans l'administration permet également de le changer après connexion. Le catalogue reste accessible sans authentification sur les réseaux autorisés.

### 13.2. Renouveler le certificat

Installer la nouvelle chaîne et la clé correspondante dans `config/tls`, contrôler les permissions, puis :

```bash
cd /srv/sersi-notices/app
docker compose exec proxy nginx -t
docker compose exec proxy nginx -s reload
```

Contrôler les dates et la chaîne depuis un poste LAN et un poste VPN. Le rechargement ne nécessite pas de reconstruire l'image de l'application.

### 13.3. Changer le mot de passe PostgreSQL ou la clé Django

Planifier l'opération avec une sauvegarde et une interruption. Pour PostgreSQL, arrêter proxy, maintenance et web ; ouvrir ensuite `docker compose exec db psql -U sersi -d sersi`, utiliser la commande interactive `\password sersi`, puis quitter avec `\q`. Reporter exactement le nouveau secret dans `.env`, puis recréer les services web, maintenance et proxy. Vérifier les connexions avant de rouvrir. Éviter les mots de passe écrits directement dans une ligne SQL ou dans l'historique du shell.

La clé Django est distincte. Son remplacement dans `.env` suivi de la recréation du web invalide les sessions et les signatures en cours, notamment les récapitulatifs d'export préparés avant le changement. Actualiser la copie de configuration sécurisée après toute rotation. Le mot de passe commun n'est pas modifié par ces deux opérations.

## 14. Reprise après perte du serveur

### 14.1. Reprise métier depuis un ZIP

Préparer une nouvelle VM, installer la version validée et les configurations, fournir un certificat valide et générer des secrets de cible. Démarrer l'application, définir le mot de passe commun puis importer, vérifier et restaurer le ZIP hors serveur selon le chapitre 8. Régler à nouveau la maintenance. Cette méthode recrée le métier mais ne rétablit pas les anciennes sessions, secrets ou réglages serveur.

### 14.2. Reprise complète depuis l'instantané

Cette procédure est destinée à une **installation de reprise neuve et isolée**, avec des volumes PostgreSQL et documentaires vides. Les commandes de restauration remplacent les objets de la base cible ; faire confirmer l'identité de la VM et le nom du projet avant de les exécuter. Ne pas ouvrir les accès collaborateurs tant que la reprise n'est pas validée.

1. Installer Docker, récupérer la révision indiquée dans `revision.txt` et préparer les dossiers standards.
2. Récupérer l'instantané complet depuis la sauvegarde hors serveur. Définir `SN_REPRISE` avec son chemin réel.
3. Rétablir `.env`, `config/` et les archives, ajuster si nécessaire l'IP et le DNS, puis charger l'image applicative sauvegardée.
4. Démarrer uniquement PostgreSQL, restaurer la base, puis les fichiers. La commande Python de restauration emploie le filtre de sécurité des archives de Python 3.12.

```bash
set -euo pipefail
cd /srv/sersi-notices/app
SN_REPRISE=/chemin/vers/instantane-complet

install -m 0600 "$SN_REPRISE/env.production" .env
cp -a "$SN_REPRISE/config/." /srv/sersi-notices/config/
cp -a "$SN_REPRISE/archives/." /srv/sersi-notices/archives/
docker image load --input "$SN_REPRISE/application-image.tar"
docker compose config --quiet
docker compose up -d --wait --wait-timeout 180 db

docker compose exec -T db pg_restore -U sersi -d sersi \
  --clean --if-exists --no-owner --no-privileges --exit-on-error \
  < "$SN_REPRISE/database.dump"
docker compose run --rm --no-deps -T web python -c \
  'import sys,tarfile; t=tarfile.open(fileobj=sys.stdin.buffer,mode="r|gz"); t.extractall("/data",filter="data")' \
  < "$SN_REPRISE/documents.tar.gz"

docker compose up -d --wait --wait-timeout 300 db web maintenance
docker compose up -d --force-recreate --no-deps proxy
docker compose exec proxy nginx -t
docker compose exec maintenance python manage.py maintenance_worker --check-health
```

Les images PostgreSQL et Nginx doivent être celles validées pour l'instantané ou des révisions compatibles déjà testées. Si la VM n'a pas d'accès aux registres, les exporter et les conserver avec l'instantané. Vérifier les compteurs, les PDF, les permissions, l'administration, les réglages de maintenance, le certificat et les règles réseau avant de basculer l'accès des salariés. Mesurer le délai de reprise et conserver le compte rendu.

## 15. Dépannage

| Symptôme | Vérifications et action |
| --- | --- |
| Le site ne répond pas | VM allumée, Docker actif, IP, DNS, VPN, pare-feu et `docker compose ps` |
| Port déjà utilisé | Vérifier les services écoutant sur 80/443 et l'IP de publication ; résoudre le conflit avant le démarrage |
| Erreur de certificat | Nom dans les SAN, dates, chaîne et confiance sur le poste ; corriger le certificat ou sa distribution |
| Boucle de redirections | Cohérence HTTPS / `X-Forwarded-Proto`, surtout avec un proxy HTTPS placé en amont |
| HTTP 400 / DisallowedHost | Nom exact dans SERSI_ALLOWED_HOSTS, sans protocole ni port, puis recréation du web |
| HTTP 403 CSRF | Origine HTTPS complète dans SERSI_TRUSTED_ORIGINS, bon Host et bonne indication HTTPS ; recharger le formulaire |
| HTTP 429 à la connexion | Attendre cinq minutes puis vérifier le mot de passe ; la limite Django derrière Nginx peut concerner tous les administrateurs |
| HTTP 502 | État du web, migrations, accès PostgreSQL ; après recréation du web, recréer le proxy pour rafraîchir sa résolution |
| Permission denied sur les archives | Présence du dossier / montage, UID/GID 10001, droits et disponibilité du NAS |
| Opération en attente / service absent | `maintenance` sain, logs et contrôle de santé ; vérifier l'espace libre et les opérations déjà en cours |
| Opération interrompue | Diagnostic dans les logs ; l'opération est marquée en échec après récupération du verrou ; relancer explicitement si approprié |
| HTTP 413 | Limite Nginx du chemin concerné ; distinguer dépôt de document et import d'un backup |
| Échec de sauvegarde : fichier disparu | Vérifier le document et son stockage, rattacher ou remettre le fichier, puis refaire une sauvegarde |
| Anciennes couleurs ou anciens styles | Vérifier la révision et la reconstruction de l'image, puis actualiser le navigateur |
| Erreur PostgreSQL après changement de .env | Le secret du rôle en base et celui de .env doivent correspondre ; appliquer la rotation du chapitre 13 |

Pour collecter un diagnostic, conserver des extraits de logs limités à l'incident, l'heure, la révision et l'état des services. Retirer les informations confidentielles avant tout partage. Le fichier `.env`, les clés TLS et les dumps complets ne doivent pas accompagner un simple ticket de support.

## 16. Limites et validation finale

| Limite de la version couverte | Valeur / comportement |
| --- | --- |
| Dépôt d'un document | 50 Mo par fichier côté application ; Nginx autorise 52m pour la requête |
| Export documentaire | 2 000 fichiers et 512 Mo avant compression |
| Import d'une sauvegarde ZIP | 2 Go côté application ; route Nginx dédiée à 2050m |
| Validation de sauvegarde | 10 Go décompressés et 20 000 entrées par défaut |
| Suppression de documents | Les anciennes copies physiques sont conservées ; purge à organiser après sauvegarde |
| Authentification | Un mot de passe administrateur commun ; pas d'attribution nominative des actions |
| Session d'administration | Huit heures ou fermeture du navigateur ; changement de mot de passe invalidant les autres sessions |
| Archivage automatique | Seulement la rétention prévue pour les sauvegardes automatiques et les copies de protection |
| Haute disponibilité | Un seul serveur dans cette architecture ; reprise par sauvegarde et restauration |

Les limites d'upload/export et de sauvegarde sont configurables dans l'environnement des services concernés et, pour les requêtes, dans Nginx. Une hausse nécessite de vérifier les temps de traitement et l'espace temporaire. Les mêmes réglages de sauvegarde doivent être appliqués au web et au service de maintenance.

**Autorisation d'ouverture à consigner :** serveur et responsable désignés ; DNS, certificat et filtrage validés ; catalogue repris ; recette LAN/VPN réussie ; première sauvegarde et copie hors serveur contrôlées ; restauration isolée réussie ; procédure de mise à jour et de reprise disponible à l'équipe informatique. Les coordonnées réelles de ces éléments restent à compléter dans la fiche d'installation.
