# SERSI Notices — version web intranet

Application documentaire pour les collaborateurs du Groupe SERSI, accessible sans compte sur le réseau interne ou le VPN. L’administration est protégée par un mot de passe commun, sans identifiant ni gestion d’utilisateurs ou de groupes. Aucun appel à un service cloud ni aucune police, bibliothèque ou ressource distante n’est nécessaire aux utilisateurs.

Service déployé sur le réseau interne : [SERSI Notices](https://sersi-notices.sersi.fr/). L’administration est accessible à [cette adresse](https://sersi-notices.sersi.fr/admin/).

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

Le navigateur télécharge une archive ZIP à extraire sur le poste utilisateur. L’administration regroupe le catalogue, les fichiers, le journal d’activité et les sauvegardes.

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

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py set_admin_password
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8766
```

Ouvrir `http://127.0.0.1:8766/` et `/admin/` pour la gestion. La commande demande un mot de passe commun d’au moins 12 caractères et sa confirmation. Aucun mot de passe par défaut n’existe ; l’administration reste inaccessible tant qu’il n’a pas été défini. Le serveur de développement est réservé aux essais sur ce poste. Le mode local génère une clé de développement dans `runtime/` ; elle n’est pas utilisée en déploiement.

Le mot de passe commun est stocké sous forme d’empreinte Django dans la base. Le lien « Mot de passe commun » permet de le changer après connexion ; la même commande permet de le réinitialiser sur le serveur. Un changement invalide les autres sessions. La session expire après huit heures ou à la fermeture du navigateur. Après cinq tentatives incorrectes depuis une même adresse réseau, la connexion est bloquée cinq minutes ; la limite est partagée entre les processus du serveur. Le proxy fourni transmet l’adresse réelle du client : un blocage reste limité à cette adresse.

Les anciens comptes Django ne permettent plus d’ouvrir l’administration. Un enregistrement technique sans mot de passe utilisable sert uniquement à conserver le journal des modifications Django ; aucune page de gestion des comptes ou des groupes n’est exposée. Ce journal conserve les dates et les changements, sans attribuer les actions à un salarié.

Les données locales et les documents restent dans `runtime/` (ignoré par Git). Pour exécuter les tests :

```powershell
.\.venv\Scripts\python.exe manage.py test catalogue
.\.venv\Scripts\python.exe manage.py check
```

## Déployer sur un serveur

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

## Transférer ou restaurer un catalogue web

Le catalogue se renseigne dans l’administration. Pour transférer un catalogue existant vers un autre serveur, créer une sauvegarde ZIP depuis **Sauvegardes et restauration**, la télécharger, puis l’importer, la vérifier et la restaurer sur la cible selon la notice de production. Le catalogue et les documents métier restent dans les volumes de données, hors du dépôt Git.

## Journaux, sauvegardes et restauration

Dans l’administration, les rubriques **Sauvegardes et restauration** et **Journal d’activité** regroupent la maintenance. Elles sont protégées par le même mot de passe commun ; les téléchargements et les fichiers de sauvegarde ne sont jamais exposés au catalogue public.

Le journal trace les modifications du catalogue, les exports et téléchargements documentaires, les connexions réussies ou refusées, les changements du mot de passe, les sauvegardes, les restaurations et les erreurs techniques. Il propose une recherche, des filtres par date, rubrique et niveau, la pagination et un export CSV. Les mots de passe, cookies, jetons, corps des requêtes et variables locales des exceptions ne sont pas enregistrés. Les erreurs techniques conservent le type d’exception et les emplacements de la pile, sans son texte potentiellement sensible. Les journaux de la plateforme (Docker, Nginx, indisponibilité complète de la base) restent accessibles avec les outils du serveur.

Une sauvegarde est un ZIP portable contenant `catalogue.json`, les documents référencés, les historiques et un manifeste SHA-256. Elle fonctionne sous SQLite et PostgreSQL sans appeler un outil externe. Elle ne contient ni mot de passe, ni session, ni fichier `.env`, ni autres sauvegardes. Les nouvelles archives utilisent le format web 2. Les archives web au format 1 restent vérifiables et restaurables ; leur ancienne métadonnée de chemin source est ignorée. Les champs inconnus restent refusés. Un serveur encore à une version antérieure de l’application ne peut pas lire le format 2. Les documents sans fichier déposé restent référencés comme tels ; un fichier référencé mais disparu physiquement fait échouer la sauvegarde. L’archive terminée est vérifiée avant d’être proposée au téléchargement. Les fichiers temporaires ne sont pas présentés comme des sauvegardes.

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

Les tests Django couvrent le catalogue public, les exports ZIP, les expirations, les fichiers manquants, les collisions de noms, les chemins, les plafonds et les mises à jour du schéma web. Ils vérifient aussi le mot de passe commun, la protection CSRF, la limitation des tentatives par client, le renouvellement et la révocation des sessions, l’absence de gestion des comptes et le journal des modifications. Les essais de maintenance couvrent les restaurations avec retour arrière en cas d’échec, les empreintes, les chemins dangereux, le service en arrière-plan, la planification, la conservation, les diagnostics filtrés et la protection des téléchargements. La CI exécute ces tests sous SQLite et PostgreSQL, puis construit et démarre Docker Compose et vérifie HTTP et HTTPS.

Le groupe d’export est obligatoire à la création ou modification d’un type de document dans l’administration. Une sauvegarde web antérieure peut encore contenir un type sans groupe : ses documents sont alors signalés comme indisponibles dans le récapitulatif, avec confirmation nécessaire pour un export incomplet. Affecter le groupe approprié depuis **Types de document** pour corriger le classement. Aucun libellé de groupe n’est interprété comme une règle métier implicite.

`SERSI_TRUST_PROXY=1` autorise Django à utiliser `X-Real-IP` pour limiter les tentatives par client et l’en-tête de protocole pour HTTPS. Ce réglage est activé dans Compose, où le port web reste privé et où Nginx remplace ces en-têtes sur toutes les routes. Ne l’activer que si toutes les requêtes passent par ce proxy de confiance, sans accès direct au service web. Hors proxy, la valeur par défaut est `0` et les en-têtes transférés sont ignorés pour la limitation des tentatives.

## Développement de l’interface et contrôles de formatage

Les outils de développement utilisent Python 3.12, Node.js 24 et pnpm 11.25.0. Ils ne sont pas nécessaires à l’exécution de l’application en production. Depuis un environnement de développement :

```sh
python -m pip install -r requirements-dev.txt
pnpm install --frozen-lockfile
pnpm exec playwright install chromium
pnpm run test:browser
pnpm run format:check
python -m djlint templates --check
```

Les parcours Playwright sont exécutés sur des tailles PC et mobile. Ils couvrent les filtres liés, les produits génériques/inactifs, la recherche, la sélection, les documents expirés, les vues liste/arborescence, la mémorisation de la vue et le téléchargement du ZIP. Le serveur de test utilise le port **8767**, un catalogue synthétique et un nouveau dossier `.tmp/browser-tests/` à chaque lancement ; il refuse de réutiliser un serveur déjà présent. Il ne charge pas le catalogue de travail. `SERSI_TEST_PYTHON` peut désigner le chemin d’un interpréteur Python et `SERSI_BROWSER_CHANNEL=msedge` permet d’utiliser Edge installé localement. La CI installe et utilise Chromium.

Pour reformater les sources : `pnpm run format` pour CSS/JavaScript et `python -m djlint templates --reformat` pour les templates Django. La configuration est versionnée ; la CI refuse les fichiers qui ne respectent pas ce format. Les dépendances JavaScript sont réservées aux tests et au formatage, sans compilation du site ni ajout de bibliothèque au navigateur des salariés.

Références : [Django 5.2 LTS](https://docs.djangoproject.com/fr/5.2/releases/5.2/), [déploiement Django](https://docs.djangoproject.com/fr/5.2/howto/deployment/checklist/), [Gunicorn](https://gunicorn.org/).

## Mise à jour du schéma documentaire

La migration `catalogue.0005_remove_document_source_path` supprime uniquement la colonne de chemin source devenue inutile. Les documents, noms de fichiers, relations et PDF sont conservés. Elle s’applique avec `python manage.py migrate`, automatiquement au démarrage du service web Docker. Comme pour chaque mise à jour, créer auparavant une sauvegarde et conserver l’instantané de reprise décrit dans la notice. Les migrations Django historiques restent versionnées pour les bases déjà installées.
