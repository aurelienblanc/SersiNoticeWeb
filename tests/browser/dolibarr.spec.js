const { test, expect } = require('playwright/test');

test('une proposition reconnue prépare les notices et télécharge le ZIP', async ({
  page,
}, testInfo) => {
  await page.goto('/');
  await page.getByRole('link', { name: 'Charger depuis Dolibarr' }).click();
  await page.getByLabel('Numéro de proposition', { exact: true }).fill('PR-OK');
  await page.getByRole('button', { name: 'Charger les produits' }).click();
  await expect(page.getByRole('heading', { name: 'Proposition PR-OK', exact: true })).toBeVisible();
  await expect(page.locator('.proposal-products li')).toHaveCount(2);
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
