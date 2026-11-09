const { test, expect } = require('playwright/test');

test('une proposition reconnue prépare les notices et télécharge le ZIP', async ({
  page,
}, testInfo) => {
  await page.goto('/');
  await page.getByRole('link', { name: 'Charger depuis Dolibarr' }).click();
  await page.getByLabel('Source Dolibarr').selectOption({ label: 'ERP de test' });
  await page.getByLabel('Numéro de proposition', { exact: true }).fill('PR-OK');
  await page.getByRole('button', { name: 'Charger les produits' }).click();
  await expect(page.getByRole('heading', { name: 'Proposition PR-OK', exact: true })).toBeVisible();
  await expect(page.locator('.proposal-products li')).toHaveCount(2);
  await expect(
    page.locator('.proposal-stats div').filter({ hasText: 'Produits reconnus' }).locator('dd'),
  ).toHaveText('2');
  await page.getByLabel('Client', { exact: true }).fill('Client test');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('proposition.png'), fullPage: true });
  await page.getByRole('button', { name: 'Préparer le dossier', exact: true }).click();
  await expect(page.locator('.archive-name')).toHaveText('Client test - PR-OK.zip');
  await expect(page.locator('#archive-list .file-row')).toHaveCount(2);
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Télécharger le ZIP' }).click();
  expect((await download).suggestedFilename()).toBe('Client test - PR-OK.zip');
});

test('les lignes sans correspondance sont visibles et demandent une confirmation', async ({
  page,
}) => {
  await page.goto('/dolibarr/');
  await page.getByLabel('Source Dolibarr').selectOption({ label: 'ERP de test' });
  await page.getByLabel('Numéro de proposition', { exact: true }).fill('PR-PARTIAL');
  await page.getByRole('button', { name: 'Charger les produits' }).click();
  await page.locator('.proposal-issues summary').click();
  await expect(
    page.getByText('Aucune correspondance dans SERSI Notices.', { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText('Ligne libre, sans produit Dolibarr associé.', { exact: true }),
  ).toBeVisible();
  const confirmation = page.getByRole('checkbox', { name: /^Je confirme la préparation/ });
  await expect(confirmation).toHaveJSProperty('required', true);
  await confirmation.check();
  await page.getByRole('button', { name: 'Préparer le dossier', exact: true }).click();
  await expect(page.locator('#archive-list .file-row')).toHaveCount(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('une autre source reconnaît le produit avec la même référence Dolibarr', async ({ page }) => {
  await page.goto('/dolibarr/');
  await page.getByLabel('Source Dolibarr').selectOption({ label: 'Autre ERP de test' });
  await page.getByLabel('Numéro de proposition').fill('PR-OK');
  await page.getByRole('button', { name: 'Charger les produits' }).click();
  await expect(page.getByText('Autre ERP de test', { exact: true })).toBeVisible();
  await expect(page.locator('.proposal-products li strong')).toHaveText(['AA-4']);
});

test('l’administration permet de créer une source et affiche une seule référence par produit', async ({
  page,
}, testInfo) => {
  await page.goto('/admin/login/');
  await page
    .getByLabel('Mot de passe commun', { exact: true })
    .fill('Browser-test-only-password-2026!');
  await page.getByRole('button', { name: 'Accéder à l’administration' }).click();
  await page.getByRole('link', { name: 'Sources Dolibarr', exact: true }).click();
  await page.getByRole('link', { name: /Ajouter source Dolibarr/i }).click();
  await page.getByLabel('Nom :', { exact: true }).fill(`ERP brouillon ${testInfo.project.name}`);
  await page
    .getByLabel('Adresse de Dolibarr')
    .fill(`https://erp-${testInfo.project.name}.example.test`);
  await page.getByLabel('Active', { exact: true }).uncheck();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole('button', { name: 'Enregistrer', exact: true }).click();
  await expect(
    page.locator('#result_list').getByRole('link', {
      name: `ERP brouillon ${testInfo.project.name}`,
      exact: true,
    }),
  ).toBeVisible();
  await page.goto('/admin/catalogue/produit/2/change/');
  const reference = page.getByLabel('Référence Dolibarr', { exact: false });
  await expect(reference).toBeVisible();
  await expect(reference).toHaveValue('ERP-BB-4');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
