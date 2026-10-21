-- Synthetic legacy schema: no business data or credentials.
CREATE TABLE Systeme (id INTEGER PRIMARY KEY, nom TEXT NOT NULL, ordre INTEGER);
CREATE TABLE Categorie (id INTEGER PRIMARY KEY, nom TEXT NOT NULL, ordre INTEGER);
CREATE TABLE Marque (id INTEGER PRIMARY KEY, nom TEXT NOT NULL, generique BOOLEAN);
CREATE TABLE TypeExport (id INTEGER PRIMARY KEY, libelle TEXT NOT NULL, ordre INTEGER);
CREATE TABLE TypeDocument (id INTEGER PRIMARY KEY, nom TEXT NOT NULL, id_type_export INTEGER);
CREATE TABLE DossierCible (id INTEGER PRIMARY KEY, nom TEXT NOT NULL, chemin_relatif TEXT NOT NULL, parent_id INTEGER, ordre INTEGER);
CREATE TABLE Produit (id INTEGER PRIMARY KEY, reference TEXT NOT NULL, nom TEXT NOT NULL, description TEXT, actif BOOLEAN, id_marque INTEGER, id_categorie INTEGER);
CREATE TABLE Document (id INTEGER PRIMARY KEY, nom TEXT NOT NULL, id_type_document INTEGER, chemin_relatif TEXT, chemin_sharepoint TEXT, date_expiration TEXT, indice TEXT);
CREATE TABLE Produit_Systeme (id_produit INTEGER, id_systeme INTEGER, PRIMARY KEY(id_produit,id_systeme));
CREATE TABLE Produit_Document (id_produit INTEGER, id_document INTEGER, PRIMARY KEY(id_produit,id_document));
CREATE TABLE Document_Dossier (id_document INTEGER, id_dossier INTEGER, PRIMARY KEY(id_document,id_dossier));

INSERT INTO Systeme VALUES (2,'Système exemple A',1),(4,'Système exemple B',2);
INSERT INTO Categorie VALUES (3,'Centrales',1),(5,'Accessoires',2);
INSERT INTO Marque VALUES (7,'Fabricant exemple',0),(9,'Marque générique exemple',1);
INSERT INTO TypeExport VALUES (7,'DOE',1),(10,'Avant-vente',2);
INSERT INTO TypeDocument VALUES (4,'Notice technique',7),(5,'Fiche commerciale',10);
INSERT INTO DossierCible VALUES (5,'Notices','Notices',NULL,1),(6,'ECS','ECS',5,1),(7,'Commercial','Commercial',NULL,2);
INSERT INTO Produit VALUES (11,'EX-001','Centrale exemple','Description exemple',1,7,3),(13,'EX-002','Module exemple','',1,7,5),(17,'EX-003','Produit inactif','',0,9,5);
INSERT INTO Document VALUES (23,'Notice exemple A',4,'Z:\Documentation\notice-a.pdf','',NULL,'A'),(29,'Notice exemple B',4,'Z:\Documentation\notice-b.pdf','',NULL,'B'),(31,'Fiche exemple',5,'Z:\Documentation\fiche.pdf','',NULL,'');
INSERT INTO Produit_Systeme VALUES (11,2),(11,4),(13,2),(17,4);
INSERT INTO Produit_Document VALUES (11,23),(11,29),(13,23),(17,31);
INSERT INTO Document_Dossier VALUES (23,5),(23,6),(29,6),(31,7);
