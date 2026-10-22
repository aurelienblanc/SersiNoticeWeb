# SERSI Notices — version web intranet

Première version fonctionnelle pour les collaborateurs du Groupe SERSI, accessible sans compte sur le réseau interne ou le VPN. L’administration est protégée par un mot de passe commun, sans identifiant ni gestion d’utilisateurs ou de groupes. Aucun appel à un service cloud ni aucune police, bibliothèque ou ressource distante n’est nécessaire aux utilisateurs.

Ce dépôt contient uniquement la version web. La version bureau est maintenue séparément dans [SersiNoticeApp](https://github.com/aurelienblanc/SersiNoticeApp). Les deux applications disposent de leur propre base ; le transfert initial se fait par import en lecture seule de la base bureau.

La palette commune au catalogue et à l’administration est définie dans `static/sersi/palette.css` : or `#C99B43`, bleu marine `#0F3057`, bordeaux `#800000`, anthracite `#303030`, gris `#D3D3D3`, noir et blanc. Les fonds et les états utilisent des déclinaisons de ces couleurs ; les boutons dorés ont un texte sombre, les actions destructives un fond bordeaux et un texte blanc.

La [notice détaillée de déploiement en production](docs/NOTICE_DEPLOIEMENT_PRODUCTION.md) décrit l’installation Linux/Docker, le HTTPS, la reprise du catalogue actuel, l’exploitation et les procédures de retour arrière. Les fichiers d’exemple correspondants sont dans `deploy/production/` ; ils ne sont activés que lorsqu’ils sont explicitement utilisés avec la configuration de base.

## Fonctionnement

- Catalogue commun, recherche par nom/référence, filtres par système, marque et catégorie. La liste des marques dépend du système choisi ; les catégories dépendent du système et de la marque. Les choix devenus incompatibles sont réinitialisés. Les marques génériques restent proposées avec la marque choisie.
- Sélection multiple, produits inactifs sur demande, nom de projet et client facultatifs.
- Prévisualisation des fichiers, téléchargement individuel et archive ZIP avec les dossiers cibles directement à la racine. Les noms de documents identiques sont conservés avec un suffixe.
- Le récapitulatif propose une vue liste et une arborescence de dossiers repliables, construites à partir du même contenu ZIP. Le choix d’affichage est mémorisé dans le navigateur ; la liste reste disponible sans JavaScript.
- Documents expirés inclus par défaut ; cocher « Exclure les documents expirés » pour les retirer. Les avertissements restent affichés dans le récapitulatif ; l’export partiel exige une confirmation. L’archive contient uniquement les documents sélectionnés.
- Le ZIP est nommé « Dossier documentaire.zip » sans client ni projet, « Client - Projet.zip » si les deux sont renseignés, ou avec le seul nom renseigné. Les caractères incompatibles avec un nom de fichier sont remplacés.
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

Exemple d’accès après configuration : `http://192.168.1.20:8080/`. La base PostgreSQL et le serveur Gunicorn n’exposent aucun port sur l’hôte ; seul Nginx le fait. La configuration de base utilise trois volumes nommés : base, documents et archives. Les archives peuvent être remplacées par un montage hôte via `SERSI_BACKUP_STORAGE`. Ne pas utiliser `docker compose down -v`, qui supprimerait les volumes nommés du projet.

Le fichier Nginx fourni sert HTTP pour les premiers essais intranet. Pour un usage régulier, configurer un certificat interne sur le proxy et passer `SERSI_HTTPS=1`, avec les URL HTTPS dans `SERSI_TRUSTED_ORIGINS`. Si le TLS se termine sur un autre proxy de l’entreprise, adapter explicitement la transmission de `X-Forwarded-Proto` : le Nginx fourni le réécrit actuellement à partir de son propre protocole. Ne pas simplement activer `SERSI_HTTPS=1` devant un proxy HTTP non adapté, ce qui provoquerait une boucle de redirection. Contrôle de configuration après adaptation : `docker compose exec web python manage.py check --deploy`.

## Reprendre la base et les fichiers actuels

Pour transférer un catalogue web déjà renseigné vers le serveur, utiliser la sauvegarde ZIP portable et la procédure de la notice de production. La procédure ci-dessous concerne une première reprise depuis une base bureau vers un catalogue vide. La base et les fichiers documentaires ne sont pas inclus dans ce dépôt web. Récupérer une copie de `data/sersi_notice.db` depuis le dépôt ou l’installation bureau. Sans copie des fichiers associés, le catalogue est consultable mais les documents restent signalés « À déposer ».

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

## Journaux, sauvegardes et restauration

Dans l’administration, les rubriques **Sauvegardes et restauration** et **Journal d’activité** regroupent la maintenance. Elles sont protégées par le même mot de passe commun ; les téléchargements et les fichiers de sauvegarde ne sont jamais exposés au catalogue public.

Le journal trace les modifications du catalogue, les exports et téléchargements documentaires, les connexions réussies ou refusées, les changements du mot de passe, les sauvegardes, les restaurations et les erreurs techniques. Il propose une recherche, des filtres par date, rubrique et niveau, la pagination et un export CSV. Les mots de passe, cookies, jetons, corps des requêtes et variables locales des exceptions ne sont pas enregistrés. Les erreurs techniques conservent le type d’exception et les emplacements de la pile, sans son texte potentiellement sensible. Les journaux de la plateforme (Docker, Nginx, indisponibilité complète de la base) restent accessibles avec les outils du serveur.

Une sauvegarde est un ZIP portable contenant `catalogue.json`, les documents référencés, les historiques et un manifeste SHA-256. Elle fonctionne sous SQLite et PostgreSQL sans appeler un outil externe. Elle ne contient ni mot de passe, ni session, ni fichier `.env`, ni autres sauvegardes. Les documents sans fichier déposé restent référencés comme tels ; un fichier référencé mais disparu physiquement fait échouer la sauvegarde. L’archive terminée est vérifiée avant d’être proposée au téléchargement. Les fichiers temporaires ne sont pas présentés comme des sauvegardes.

Le service de maintenance exécute les opérations en arrière-plan et publie leur progression. Par défaut : sauvegarde quotidienne à **02:00, heure de Paris**, conservation des **7 dernières sauvegardes automatiques** et des **90 derniers jours de journaux**. Ces paramètres sont modifiables dans l’administration. Les sauvegardes manuelles et importées ne sont pas supprimées automatiquement ; les trois dernières copies de protection avant restauration sont conservées séparément. La première planification concerne le prochain jour ; après un arrêt, une sauvegarde quotidienne manquée est rattrapée au redémarrage du service.

Docker Compose lance automatiquement le service `maintenance`. Pour les essais Windows, lancer dans un second terminal, depuis le dépôt :

```powershell
.\.venv\Scripts\python.exe manage.py maintenance_worker
```

Le PC ou le serveur doit rester allumé pour exécuter une sauvegarde planifiée. La page affiche si le service répond. Une opération interrompue est signalée en échec au prochain démarrage, sans rejouer automatiquement une restauration.

Pour créer une sauvegarde depuis une commande :

```sh
docker compose exec web python manage.py backup_catalogue
```

Le script suivant crée la même sauvegarde et en copie une archive sur l’hôte, sans arrêter le catalogue :

```sh
sh deploy/backup.sh ./backups
```

Le stockage est `runtime/backups` en local et le volume Docker dédié `archives` en déploiement. `SERSI_BACKUP_STORAGE` dans `.env` peut désigner un chemin absolu vers un dossier du serveur ou un NAS déjà monté ; ce dossier doit être accessible en écriture à l’UID 10001. Les volumes de sauvegarde et de documents restent distincts. Conserver aussi une copie hors de l’équipement et le fichier `.env` séparément.

Pour restaurer : importer si nécessaire un ZIP dans la page de maintenance, attendre sa vérification, choisir **Restaurer**, saisir le mot de passe commun et `RESTAURER`. Le service recontrôle les empreintes, refuse les chemins dangereux, les liens, les modèles non autorisés, les relations invalides et les archives trop volumineuses, puis crée une sauvegarde de protection. Il prépare les fichiers sous de nouveaux noms avant de remplacer le catalogue et ses relations dans une transaction. Un échec annule les changements de base et retire uniquement ces nouvelles copies. Le mot de passe courant, les sessions, les réglages de maintenance et les archives disponibles restent conservés. Le journal courant est conservé et complété avec les événements de la sauvegarde.

Le catalogue est momentanément indisponible durant une restauration ; la page de suivi reste accessible. La suppression d’une archive et le nettoyage manuel du journal demandent également le mot de passe et une confirmation explicite. Les anciennes copies physiques de fichiers documentaires restent présentes après restauration ; leur purge physique n’est pas automatique.

Les limites par défaut sont de 2 Go pour l’import, 10 Go décompressés et 20 000 entrées par sauvegarde. `SERSI_BACKUP_DIR`, `SERSI_BACKUP_UPLOAD_BYTES` et `SERSI_BACKUP_MAX_BYTES` permettent d’adapter le stockage et les tailles ; conserver les mêmes réglages dans les services web et maintenance et adapter la limite Nginx en cas de modification. Les anciennes paires `database.dump` / `documents.tar.gz` ne sont pas des ZIP compatibles avec cet écran et nécessitent leur procédure PostgreSQL d’origine.

## Limites et réglages

Un fichier déposé depuis l’administration est limité à 50 Mo. Un export est limité à 2 000 fichiers et 512 Mo avant compression ; la génération utilise un fichier temporaire sur disque au-delà de 8 Mo. Les variables `SERSI_MAX_UPLOAD_BYTES`, `SERSI_EXPORT_MAX_BYTES` et `SERSI_EXPORT_MAX_FILES` peuvent être ajoutées à l’environnement du service `web`. Si la taille de dépôt change, adapter aussi `client_max_body_size` dans Nginx.

Les anciens fichiers restent conservés dans le volume après remplacement ou suppression d’un document, afin d’éviter une suppression physique accidentelle. Leur purge éventuelle doit être précédée d’une sauvegarde. L’historique des exports conserve le nom du projet et les compteurs. Sans connexion des collaborateurs, aucun suivi nominatif des exports n’est possible.

Les 49 tests couvrent le catalogue public, les exports ZIP, les expirations, les fichiers manquants, les collisions de noms, les chemins, les plafonds et la migration du format SQLite de la version bureau. Ils vérifient aussi le mot de passe commun, la protection CSRF, la limitation des tentatives, le renouvellement et la révocation des sessions, l’absence de gestion des comptes et le journal des modifications. Les essais de maintenance couvrent les restaurations avec retour arrière en cas d’échec, les empreintes, les chemins dangereux, le service en arrière-plan, la planification, la conservation et la protection des téléchargements. La CI exécute ces tests sous SQLite et PostgreSQL, puis construit et démarre Docker Compose et vérifie les réponses HTTP du catalogue et du contrôle de santé. Docker n’est pas installé sur le poste de préparation ; le serveur définitif et ses sauvegardes restent à valider dans leur environnement réseau.

Références : [Django 5.2 LTS](https://docs.djangoproject.com/fr/5.2/releases/5.2/), [déploiement Django](https://docs.djangoproject.com/fr/5.2/howto/deployment/checklist/), [Gunicorn](https://gunicorn.org/).

## Origine et indépendance du dépôt

Le code web provient du travail de migration au commit [76a3195](https://github.com/aurelienblanc/SersiNoticeApp/commit/76a31951b95222aac88fac1a12736cf9a6615f23). Ce dépôt possède désormais son propre historique, ses dépendances, ses migrations, ses tests et son déploiement. Il ne contient ni code Qt/PySide6, ni exécutables bureau, ni base métier, ni identifiants. Les tests utilisent une base SQLite synthétique fournie dans `catalogue/testdata/` et ne nécessitent aucun clone de la version bureau.
