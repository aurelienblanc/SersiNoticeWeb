# SERSI Notice — version web intranet

Première version fonctionnelle pour les collaborateurs du Groupe SERSI, accessible sans compte sur le réseau interne ou le VPN. L’administration est protégée par un mot de passe commun, sans identifiant ni gestion d’utilisateurs ou de groupes. Aucun appel à un service cloud ni aucune police, bibliothèque ou ressource distante n’est nécessaire aux utilisateurs.

Ce dépôt contient uniquement la version web. La version bureau est maintenue séparément dans [SersiNoticeApp](https://github.com/aurelienblanc/SersiNoticeApp). Les deux applications disposent de leur propre base ; le transfert initial se fait par import en lecture seule de la base bureau.

## Fonctionnement

- Catalogue commun, recherche par nom/référence, filtres par système, marque et catégorie. Les marques génériques restent proposées avec la marque choisie.
- Sélection multiple, produits inactifs sur demande, nom de projet et client facultatifs.
- Prévisualisation des fichiers, téléchargement individuel et archive ZIP avec les dossiers cibles directement à la racine. Le nom du projet sert au nom de l’archive. Les noms identiques sont conservés avec un suffixe.
- Documents expirés exclus par défaut ; inclusion possible sur demande explicite. Les avertissements restent affichés dans le récapitulatif ; l’export partiel exige une confirmation. L’archive contient uniquement les documents sélectionnés.
- Administration aux couleurs SERSI : tableau de bord, navigation par rubrique, formulaires organisés et états des fichiers. Gestion des systèmes, marques, catégories, produits, documents, types et dossiers. Dépôt des fichiers, journal des modifications et historique des exports. Aucun nom de salarié n’est demandé.
- Import en lecture seule du catalogue SQLite existant, copie optionnelle des fichiers et rapport CSV des documents à rattacher. L’ancien mot de passe de configuration n’est pas importé.

Le navigateur télécharge une archive : l’écriture directe d’un dossier sur le poste utilisateur est remplacée par l’extraction du ZIP. Les fenêtres Qt de restauration, de logs et de recherche de chemins sont remplacées par l’administration, les commandes de rattachement et les sauvegardes serveur décrites ci-dessous.

## Architecture retenue

Python 3.12 + Django 5.2 LTS, interface HTML/CSS/JavaScript en français, PostgreSQL en déploiement et SQLite pour les essais locaux. Django fournit l’administration, les sessions, la validation et la protection CSRF. Gunicorn exécute l’application derrière Nginx. Docker Compose assure le lancement sur une machine disposant d’un moteur de conteneurs Linux.

```text
Collaborateurs (LAN / VPN)
          |
  Nginx — IP interne du serveur
          |
      Django / Gunicorn
        /          \
 PostgreSQL     Volume documentaire
```

Les fichiers ne sont pas servis par un répertoire web public. Les téléchargements passent par Django et sont forcés en pièces jointes. Le catalogue et les documents restent volontairement accessibles à toute personne pouvant joindre le service : la restriction LAN/VPN repose sur le pare-feu et le réseau du serveur. Les paramètres d’hôte Django ne remplacent pas cette restriction.

## Essayer sur Windows

Depuis la racine du dépôt, avec Python 3.12 ou supérieur compatible Django :

Les commandes d’import ci-dessous supposent que les deux dépôts sont clonés côte à côte. Adapter le chemin de la base source si elle se trouve ailleurs. L’application web et ses tests fonctionnent seuls ; l’import est uniquement nécessaire pour reprendre le catalogue existant.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py import_legacy ..\SersiNoticeApp\data\sersi_notice.db --dry-run
.\.venv\Scripts\python.exe manage.py import_legacy ..\SersiNoticeApp\data\sersi_notice.db
.\.venv\Scripts\python.exe manage.py set_admin_password
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8766
```

Ouvrir `http://127.0.0.1:8766/` et `/admin/` pour la gestion. La commande demande un mot de passe commun d’au moins 12 caractères et sa confirmation. Aucun mot de passe par défaut n’existe ; l’administration reste inaccessible tant qu’il n’a pas été défini. Le serveur de développement est réservé aux essais sur ce poste. Le mode local génère une clé de développement dans `runtime/` ; elle n’est pas utilisée en déploiement.

Le mot de passe commun est stocké sous forme d’empreinte Django dans la base. Le lien « Mot de passe commun » permet de le changer après connexion ; la même commande permet de le réinitialiser sur le serveur. Un changement invalide les autres sessions. La session expire après huit heures ou à la fermeture du navigateur. Après cinq tentatives incorrectes depuis une même adresse réseau, la connexion est bloquée cinq minutes ; la limite est partagée entre les processus du serveur. Derrière le proxy fourni, cette adresse est celle du proxy : le blocage concerne donc l’ensemble des administrateurs pendant cette durée.

Les anciens comptes Django ne permettent plus d’ouvrir l’administration. Un enregistrement technique sans mot de passe utilisable sert uniquement à conserver le journal des modifications Django ; aucune page de gestion des comptes ou des groupes n’est exposée. Ce journal conserve les dates et les changements, sans attribuer les actions à un salarié.

Les données locales, documents et rapports restent dans `runtime/` (ignoré par Git). Pour exécuter les tests :

```powershell
.\.venv\Scripts\python.exe manage.py test catalogue
.\.venv\Scripts\python.exe manage.py check
```

## Déployer sur le futur serveur

Un serveur ou une VM avec Docker et le plugin Compose peut lancer les conteneurs. Sur un hôte Windows ou un NAS, vérifier au préalable sa prise en charge des conteneurs Linux ; ce déploiement n’a pas encore été validé sur ces équipements.

À la racine du dépôt :

1. Copier `.env.example` dans `.env`.
2. Générer deux secrets distincts, par exemple deux fois `python -c "import secrets; print(secrets.token_urlsafe(64))"`, et les renseigner dans `SERSI_SECRET_KEY` et `POSTGRES_PASSWORD`.
3. Pour les premiers essais, laisser l’adresse d’écoute sur `127.0.0.1`. Pour l’accès des collaborateurs, renseigner **l’IP privée du serveur** dans `SERSI_BIND_ADDRESS`, cette IP ou son nom DNS dans `SERSI_ALLOWED_HOSTS`, et les URL complètes avec port dans `SERSI_TRUSTED_ORIGINS`.
4. Autoriser le port choisi uniquement depuis les sous-réseaux de l’entreprise et du VPN dans le pare-feu. Ne pas configurer de redirection Internet vers ce service.
5. Lancer puis définir le mot de passe commun de l’administration :

```sh
docker compose up -d --build
docker compose exec web python manage.py set_admin_password
docker compose ps
```

Exemple d’accès après configuration : `http://192.168.1.20:8080/`. La base PostgreSQL et le serveur Gunicorn n’exposent aucun port sur l’hôte ; seul Nginx le fait. Les données sont conservées dans deux volumes nommés. Ne pas utiliser `docker compose down -v`, qui supprimerait ces volumes.

Le fichier Nginx fourni sert HTTP pour les premiers essais intranet. Pour un usage régulier, configurer un certificat interne sur le proxy et passer `SERSI_HTTPS=1`, avec les URL HTTPS dans `SERSI_TRUSTED_ORIGINS`. Si le TLS se termine sur un autre proxy de l’entreprise, adapter explicitement la transmission de `X-Forwarded-Proto` : le Nginx fourni le réécrit actuellement à partir de son propre protocole. Ne pas simplement activer `SERSI_HTTPS=1` devant un proxy HTTP non adapté, ce qui provoquerait une boucle de redirection. Contrôle de configuration après adaptation : `docker compose exec web python manage.py check --deploy`.

## Reprendre la base et les fichiers actuels

La base de la version bureau analysée contient 260 produits et 467 références documentaires. Cette base et les fichiers documentaires ne sont pas inclus dans ce dépôt web. Récupérer une copie de `data/sersi_notice.db` depuis le dépôt ou l’installation bureau, puis utiliser l’import ci-dessous. Sans copie des fichiers associés, le catalogue est consultable mais les documents restent signalés « À déposer ».

L’import initial exige un catalogue web vide. Il ne remplace ni ne fusionne des données web existantes. Les identifiants et les trois tables de relations sont conservés. Un rapport est écrit dans le volume de données. `--dry-run` valide les données puis annule la transaction, sans copie des documents.

Pour importer sur le serveur : copier d’abord la base dans le conteneur, puis lancer la simulation et l’import. Ne pas réimporter une base sur le catalogue déjà rempli.

```sh
docker compose cp ../SersiNoticeApp/data/sersi_notice.db web:/data/legacy.sqlite
docker compose exec web python manage.py import_legacy /data/legacy.sqlite --dry-run
docker compose exec web python manage.py import_legacy /data/legacy.sqlite
docker compose cp web:/data/rapport-import.csv ./rapport-import.csv
```

Pour copier les documents dès l’import, ajouter au service `web` un montage en lecture seule vers leur répertoire serveur, par exemple `- /srv/sersi-documents:/legacy-documents:ro`, puis :

```sh
docker compose exec web python manage.py import_legacy /data/legacy.sqlite \
  --documents-root /legacy-documents \
  --path-map 'Z:\Documentation=/legacy-documents' --dry-run
```

Retirer `--dry-run` pour importer effectivement dans un catalogue vide. Si les métadonnées ont déjà été importées, utiliser la commande dédiée, qui ne recopie que les documents absents :

```sh
docker compose exec web python manage.py attach_legacy_files /legacy-documents \
  --path-map 'Z:\Documentation=/legacy-documents' --dry-run
```

Retirer `--dry-run` pour rattacher les fichiers. Les chemins ne sont acceptés qu’à l’intérieur de `--documents-root`. À défaut d’une correspondance de chemin, un nom de fichier **unique** peut être retrouvé dans ce répertoire. Deux fichiers portant le même nom nécessitent une correspondance exacte ; aucun choix arbitraire n’est effectué. Les documents sont copiés dans le volume de l’application : les fichiers originaux ne sont pas modifiés. SharePoint est conservé comme métadonnée, sans téléchargement automatique ni utilisation des identifiants d’un salarié.

## Sauvegarder et restaurer

Sur le serveur Linux, depuis la racine du dépôt :

```sh
sh deploy/backup.sh ./backups
```

Le script suspend brièvement le web et le proxy, exporte PostgreSQL et archive le volume documentaire, puis redémarre les services. Il faut sauvegarder **les deux fichiers du même dossier horodaté**, ainsi que le fichier `.env` conservé séparément dans un emplacement protégé. Copier les sauvegardes vers un stockage distinct du serveur et vérifier régulièrement une restauration. La planification et la rétention seront à configurer sur le serveur retenu.

Pour restaurer sur une instance de test, après avoir sauvegardé son état courant :

```sh
docker compose stop proxy web
docker compose exec -T db pg_restore -U sersi -d sersi --clean --if-exists < backups/HORODATAGE/database.dump
docker compose run --rm -T --no-deps --entrypoint tar web -C /data -xzf - < backups/HORODATAGE/documents.tar.gz
docker compose start web proxy
```

Cette restauration remplace les données de l’instance cible. Conserver une copie antérieure pour revenir en arrière. Le passage en production nécessite encore le choix du serveur, la récupération des vrais fichiers, la configuration réseau/HTTPS et un essai de sauvegarde/restauration sur cette infrastructure.

## Limites et réglages

Un fichier déposé depuis l’administration est limité à 50 Mo. Un export est limité à 2 000 fichiers et 512 Mo avant compression ; la génération utilise un fichier temporaire sur disque au-delà de 8 Mo. Les variables `SERSI_MAX_UPLOAD_BYTES`, `SERSI_EXPORT_MAX_BYTES` et `SERSI_EXPORT_MAX_FILES` peuvent être ajoutées à l’environnement du service `web`. Si la taille de dépôt change, adapter aussi `client_max_body_size` dans Nginx.

Les anciens fichiers restent conservés dans le volume après remplacement ou suppression d’un document, afin d’éviter une suppression physique accidentelle. Leur purge éventuelle doit être précédée d’une sauvegarde. L’historique des exports conserve le nom du projet et les compteurs ; la rétention reste à définir. Sans connexion des collaborateurs, aucun suivi nominatif des exports n’est possible.

Les 30 tests couvrent le catalogue public, les exports ZIP, les expirations, les fichiers manquants, les collisions de noms, les chemins, les plafonds et la migration du format SQLite de la version bureau. Ils vérifient aussi le mot de passe commun, la protection CSRF, la limitation des tentatives, le renouvellement et la révocation des sessions, l’absence de gestion des comptes et le journal des modifications. La CI exécute ces tests sous SQLite et PostgreSQL, puis construit et démarre Docker Compose et vérifie les réponses HTTP du catalogue et du contrôle de santé. Docker n’est pas installé sur le poste de préparation ; le serveur définitif et ses sauvegardes restent à valider dans leur environnement réseau.

Références : [Django 5.2 LTS](https://docs.djangoproject.com/fr/5.2/releases/5.2/), [déploiement Django](https://docs.djangoproject.com/fr/5.2/howto/deployment/checklist/), [Gunicorn](https://gunicorn.org/).

## Origine et indépendance du dépôt

Le code web provient du travail de migration au commit [76a3195](https://github.com/aurelienblanc/SersiNoticeApp/commit/76a31951b95222aac88fac1a12736cf9a6615f23). Ce dépôt possède désormais son propre historique, ses dépendances, ses migrations, ses tests et son déploiement. Il ne contient ni code Qt/PySide6, ni exécutables bureau, ni base métier, ni identifiants. Les tests utilisent une base SQLite synthétique fournie dans `catalogue/testdata/` et ne nécessitent aucun clone de la version bureau.
