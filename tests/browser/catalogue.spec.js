const { test, expect } = require('playwright/test');

const row = (page, reference) =>
  page.locator('[data-product]').filter({ has: page.getByText(reference, { exact: true }) });
const options = (locator) => locator.locator('option').allTextContents();

test.beforeEach(async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#visible-count')).toHaveText('4 produits');
});

test('les filtres liés réinitialisent les choix devenus impossibles', async ({ page }) => {
  await page.locator('#id_systeme').selectOption({ label: 'Type 4' });
  await page.locator('#id_marque').selectOption({ label: 'Marque B' });
  await expect
    .poll(() => options(page.locator('#category-filter')))
    .toEqual(['Toutes les catégories', 'Accessoires', 'Périphériques']);
  await page.locator('#category-filter').selectOption({ label: 'Périphériques' });
  await row(page, 'BB-4').getByRole('checkbox').check();
  await page.locator('#id_systeme').selectOption({ label: 'SSI' });
  await expect(page.locator('#id_marque')).toHaveValue('');
  await expect(page.locator('#category-filter')).toHaveValue('');
  await expect
    .poll(() => options(page.locator('#id_marque')))
    .toEqual(['Toutes les marques', 'Commun', 'Marque A']);
  await expect
    .poll(() => options(page.locator('#category-filter')))
    .toEqual(['Toutes les catégories', 'Accessoires', 'Centrales']);
  await expect(row(page, 'BB-4').locator('input[type=checkbox]')).not.toBeChecked();
  await expect(page.locator('#selected-count')).toHaveText('0');
});

test('marque générique, inactifs et recherche conservent une sélection cohérente', async ({
  page,
}) => {
  await page.locator('#id_systeme').selectOption({ label: 'Type 4' });
  await page.locator('#id_marque').selectOption({ label: 'Marque A' });
  await expect(row(page, 'GEN')).toBeVisible();
  await expect(row(page, 'AA-OLD')).toBeHidden();
  await page.locator('#include-inactive').check();
  await expect(row(page, 'AA-OLD')).toBeVisible();
  await expect.poll(() => options(page.locator('#category-filter'))).toContain('Périphériques');
  await page.locator('#include-inactive').uncheck();
  await page.locator('#select-visible').check();
  await expect(page.locator('#selected-count')).toHaveText('2');
  await page.locator('#product-search').fill('ACCESSOIRE');
  await expect(page.locator('#visible-count')).toHaveText('1 produit');
  await expect(page.locator('#selected-count')).toHaveText('2');
  await page.getByRole('button', { name: 'Tout désélectionner' }).click();
  await expect(page.locator('#selected-count')).toHaveText('0');
  await expect(page.locator('#prepare-button')).toBeDisabled();
  await page.locator('#product-search').fill('introuvable');
  await expect(page.locator('#no-results')).toBeVisible();
});

test('le récapitulatif bascule entre liste et dossiers, conserve le choix et télécharge le ZIP', async ({
  page,
}) => {
  await row(page, 'AA-4').getByRole('checkbox').check();
  await page.locator('#id_client').fill('Client Test');
  await page.locator('#id_projet').fill('Projet Test');
  await page.getByRole('button', { name: 'Préparer le dossier' }).click();
  await expect(page.locator('.archive-name')).toHaveText('Client Test - Projet Test.zip');
  await expect(page.locator('#archive-list')).toBeVisible();
  await page.getByRole('button', { name: 'Arborescence', exact: true }).click();
  await expect(page.locator('#archive-list')).toBeHidden();
  const tree = page.locator('#archive-tree');
  await expect(tree).toBeVisible();
  await expect(tree.getByText('AA-4.pdf', { exact: true })).toBeVisible();
  await tree.locator('summary').first().click();
  await expect(tree.getByText('AA-4.pdf', { exact: true })).toBeHidden();
  await tree.locator('summary').first().click();
  await expect(tree.getByText('AA-4.pdf', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Liste', exact: true }).click();
  await expect(page.locator('#archive-list')).toBeVisible();
  await page.getByRole('button', { name: 'Arborescence', exact: true }).click();
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Télécharger le ZIP' }).click();
  expect((await download).suggestedFilename()).toBe('Client Test - Projet Test.zip');
  await page.goto('/');
  await row(page, 'GEN').getByRole('checkbox').check();
  await page.getByRole('button', { name: 'Préparer le dossier' }).click();
  await expect(page.getByRole('button', { name: 'Arborescence', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await expect(page.locator('#archive-tree')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
});

test('les documents expirés sont inclus par défaut et exclus à la demande', async ({ page }) => {
  await row(page, 'BB-4').getByRole('checkbox').check();
  await page.getByRole('button', { name: 'Préparer le dossier' }).click();
  await expect(
    page.getByText('Des documents expirés sont inclus dans cette sélection.'),
  ).toBeVisible();
  await expect(page.locator('#archive-list .file-row')).toHaveCount(1);
  await page.goto('/');
  await row(page, 'BB-4').getByRole('checkbox').check();
  await page.locator('.advanced summary').click();
  await page.locator('#exclude-expired').check();
  await page.getByRole('button', { name: 'Préparer le dossier' }).click();
  await expect(page.getByText('Aucun fichier disponible.', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Télécharger le ZIP' })).toBeDisabled();
});

test('le formulaire administration garde ses contrôles visibles sur PC et mobile', async ({
  page,
}, testInfo) => {
  await page.goto('/admin/login/');
  await page
    .getByLabel('Mot de passe commun', { exact: true })
    .fill('Browser-test-only-password-2026!');
  await page.getByRole('button', { name: 'Accéder à l’administration' }).click();
  await expect(page).toHaveURL(/\/admin\/$/);
  await page.goto('/admin/catalogue/document/1/change/');
  const remove = page.locator('.submit-row a.deletelink');
  await expect(remove).toBeVisible();
  expect((await remove.boundingBox()).height).toBeGreaterThanOrEqual(40);
  expect((await page.locator('#id_type_document').boundingBox()).height).toBeGreaterThanOrEqual(35);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({ path: testInfo.outputPath('administration.png'), fullPage: true });
});
