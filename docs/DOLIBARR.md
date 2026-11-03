# Préparer un dossier à partir de Dolibarr

## Correspondances produits

Dans **Administration → Produits**, renseigner **Référence Dolibarr** avec la référence exacte du produit de l’ERP. Le champ est facultatif et reste vide sur les produits existants. La référence habituelle de SERSI Notices reste inchangée. La colonne et la recherche de l’administration permettent de retrouver les correspondances.

Une référence ERP doit désigner un seul produit du catalogue pour être reconnue automatiquement. Une référence absente ou présente sur plusieurs fiches est signalée dans le récapitulatif. Aucune correspondance n’est devinée à partir du nom ou d’une référence partielle.

## Configurer la connexion

Activer le module REST de Dolibarr et utiliser la clé API d’un utilisateur autorisé à lire les propositions commerciales et les produits. Les appels de ce connecteur sont exclusivement des requêtes GET. Il est compatible avec les routes de Dolibarr 22.0.5 : [propositions par référence](https://github.com/Dolibarr/dolibarr/blob/22.0.5/htdocs/comm/propal/class/api_proposals.class.php) et [produits](https://github.com/Dolibarr/dolibarr/blob/22.0.5/htdocs/product/class/api_products.class.php).

Dans le fichier `.env` du serveur, hors du dépôt :

```dotenv
SERSI_DOLIBARR_URL=https://dolibarr.entreprise.example
SERSI_DOLIBARR_NAME=Mon ERP Dolibarr
SERSI_DOLIBARR_API_KEY=cle-api-de-lecture
```

L’URL peut contenir le sous-dossier de l’ERP. Le connecteur ajoute `/api/index.php` ; une URL comprenant déjà ce suffixe est également acceptée. Les redirections HTTP ne sont pas suivies afin de conserver la clé sur le serveur configuré. Le nom est affiché aux utilisateurs. Cette première connexion concerne un ERP configuré côté serveur.

Après la mise à jour du code selon la notice de production, reconstruire et relancer les services :

```bash
docker compose up -d --build --wait --wait-timeout 300 db web maintenance
```

Le démarrage applique la migration `0006_produit_reference_dolibarr`. Pour une exécution Python hors Docker, les mêmes variables doivent être présentes dans l’environnement du processus. `SERSI_DOLIBARR_API_KEY_FILE` peut alors indiquer un fichier contenant uniquement la clé, à la place de `SERSI_DOLIBARR_API_KEY` ; il est lu à chaque chargement de proposition. Une clé fournie directement dans l’environnement est prioritaire.

La clé n’est pas transmise au navigateur, placée dans les URL, incluse dans les sauvegardes ou journalisée. Les journaux enregistrent la référence de proposition et les compteurs de produits/lignes signalées. La réponse complète de l’ERP n’est pas conservée.

## Utilisation

1. Depuis la création d’un dossier, cliquer sur **Charger depuis Dolibarr**, ou ouvrir `/dolibarr/`.
2. Saisir le numéro exact de la proposition commerciale.
3. Examiner les produits reconnus et les lignes à vérifier. Les lignes libres sans produit ERP ne peuvent pas fournir de référence documentaire. Les produits répétés sont regroupés ; un produit inactif reconnu est conservé et signalé.
4. Choisir les documents à inclure, le nom du projet et éventuellement le client. Le projet prend initialement le numéro de proposition. Les documents expirés sont inclus sauf si l’option d’exclusion est cochée.
5. S’il reste des lignes signalées, confirmer explicitement la préparation avec les seuls produits reconnus. Si aucun produit n’est reconnu, renseigner les correspondances dans l’administration puis recharger la proposition.
6. Préparer le dossier, vérifier les fichiers dans le récapitulatif habituel puis télécharger le ZIP.

Les correspondances sont vérifiées à nouveau avant la préparation. Un récapitulatif expiré, modifié ou devenu incompatible avec le catalogue doit être rechargé. Les erreurs d’accès, propositions introuvables et délais réseau sont affichés sans dévoiler la clé ou le contenu technique des réponses.

## Sauvegardes

Les nouvelles sauvegardes utilisent le format web **3** et conservent `reference_dolibarr`. Les archives web **1 et 2** restent lisibles : la référence Dolibarr absente y est initialisée à une chaîne vide. Une application antérieure à cette évolution ne lit pas le format 3 ; conserver l’instantané complet avant mise à jour pour un retour arrière.
