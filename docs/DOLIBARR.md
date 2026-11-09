# Préparer un dossier à partir de Dolibarr

## Ajouter une source

Activer le module REST de Dolibarr et utiliser la clé API d’un utilisateur autorisé à lire les propositions commerciales et les produits. Les appels de ce connecteur sont exclusivement des requêtes GET. Il est compatible avec les routes de Dolibarr 22.0.5 : [propositions par référence](https://github.com/Dolibarr/dolibarr/blob/22.0.5/htdocs/comm/propal/class/api_proposals.class.php) et [produits](https://github.com/Dolibarr/dolibarr/blob/22.0.5/htdocs/product/class/api_products.class.php).

1. Ouvrir **Administration → Sources Dolibarr → Ajouter source Dolibarr**.
2. Indiquer le nom affiché aux collaborateurs et l’adresse HTTPS de l’ERP. L’adresse peut comprendre un sous-dossier ou se terminer par `/api/index.php`.
3. Saisir la clé API, cocher **Active** et enregistrer. Une source peut être enregistrée inactive avant de disposer de sa clé. Seules les sources actives avec une clé sont proposées à l’import.
4. Répéter l’opération pour chaque ERP. Les modifications prennent effet dès l’enregistrement.

Le champ **Clé API** reste vide lors d’une modification. Laisser le champ vide conserve la clé pour la même adresse. Si l’adresse change, fournir une clé pour le nouvel ERP avant d’activer la source. Les clés sont chiffrées côté serveur avec une clé dérivée de `SERSI_SECRET_KEY` et liée à l’adresse de l’ERP. Si `SERSI_SECRET_KEY` change, ressaisir les clés. Le connecteur envoie la clé uniquement dans l’en-tête d’authentification à l’adresse configurée et refuse les redirections.

Pour retirer temporairement un ERP du formulaire d’import, décocher **Active**. La suppression d’une source retire aussi ses correspondances produits.

## Correspondances produits

Dans **Administration → Produits**, ouvrir un produit. Dans **Références Dolibarr**, ajouter une ligne par ERP concerné, choisir la source et saisir la référence exacte dans cet ERP. La recherche de l’administration retrouve aussi les références Dolibarr.

Une même référence peut désigner des produits différents dans deux ERP. Si elle désigne plusieurs produits pour la même source, le récapitulatif signale l’ambiguïté. Une référence absente déclenche aussi un signalement.

## Utilisation

1. Depuis la création d’un dossier, cliquer sur **Charger depuis Dolibarr**, ou ouvrir `/dolibarr/`.
2. Choisir la source Dolibarr et saisir le numéro exact de la proposition commerciale.
3. Examiner les produits reconnus et les lignes à vérifier. Les lignes libres sans produit ERP ne peuvent pas fournir de référence documentaire. Les produits répétés sont regroupés ; un produit inactif reconnu est conservé et signalé.
4. Choisir les documents à inclure, le nom du projet et éventuellement le client. Le projet prend initialement le numéro de proposition. Les documents expirés sont inclus sauf si l’option d’exclusion est cochée.
5. S’il reste des lignes signalées, confirmer explicitement la préparation avec les seuls produits reconnus. Si aucun produit n’est reconnu, renseigner les correspondances dans l’administration puis recharger la proposition.
6. Préparer le dossier, vérifier les fichiers dans le récapitulatif habituel puis télécharger le ZIP.

Les correspondances et la source sont vérifiées à nouveau avant la préparation. Un récapitulatif expiré, modifié ou devenu incompatible avec le catalogue doit être rechargé. Le journal enregistre la source, la référence de proposition chargée et les compteurs.

## Mise à jour depuis la connexion unique

Lors de la migration, le nom, l’adresse et la clé de l’ancienne connexion sont repris depuis les variables `SERSI_DOLIBARR_*` si elles sont renseignées. Les correspondances existantes sont transférées vers cette source. En l’absence de clé, la source reste inactive. Si aucune adresse valide n’est disponible, les références existantes sont rattachées à une source inactive **Dolibarr historique** à identifier dans l’administration. Après migration, les sources se gèrent depuis l’administration et les anciennes variables peuvent être retirées du fichier `.env`.

## Sauvegardes

Les sauvegardes web au format **4** conservent les sources et leurs correspondances produits. Lors d’une restauration, une source est reconnue par son adresse et conserve ses réglages et sa clé sur le serveur. Une source absente est ajoutée inactive, prête à recevoir sa clé. Les clés API sont exclues du ZIP.

Les archives web **1 à 3** restent restaurables. Les références du format 3 sont reprises sous **Dolibarr historique**, à vérifier avant activation, car ce format ne contenait pas l’adresse de l’ERP. Une version antérieure de l’application ne lit pas le format 4. Conserver l’instantané complet de la base et le fichier `.env` avant la mise à jour pour un retour arrière.
