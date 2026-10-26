const { test, expect } = require('playwright/test');

test('la navigation donne accès à la recherche et conserve les filtres dans l’URL', async ({
  page,
}, testInfo) => {
  await page.goto('/');
  await page.getByRole('link', { name: 'Documents', exact: true }).click();
  await expect(page).toHaveURL(/\/documents\/$/);
  await expect(page.getByRole('link', { name: 'Documents', exact: true })).toHaveAttribute(
    'aria-current',
    'page',
  );
  await page.getByLabel('Marque', { exact: true }).selectOption({ label: 'Marque A' });
  await expect(page.locator('#document-references option')).toHaveCount(3);
  await page.getByLabel('Référence produit', { exact: true }).fill('aa-4');
  await page.getByRole('button', { name: 'Rechercher', exact: true }).click();
  await expect(page.locator('.document-card')).toHaveCount(1);
  await expect(page.locator('.document-card h3')).toHaveText('Notice AA-4');
  await expect(page.getByLabel('Référence produit', { exact: true })).toHaveValue('aa-4');
  await expect(page).toHaveURL(/reference=aa-4/);
  await expect(
    page.getByRole('link', { name: 'Consulter Notice AA-4 (nouvel onglet)', exact: true }),
  ).toHaveAttribute('target', '_blank');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({ path: testInfo.outputPath('documents.png'), fullPage: true });
  await page.getByRole('link', { name: 'Dossier documentaire', exact: true }).click();
  await expect(page.locator('#selection-form')).toBeVisible();
});

test('la consultation PDF est servie dans le navigateur et le téléchargement reste disponible', async ({
  page,
}) => {
  await page.goto('/documents/?reference=AA-4');
  const viewLink = page.getByRole('link', {
    name: 'Consulter Notice AA-4 (nouvel onglet)',
    exact: true,
  });
  const response = await page.request.get(await viewLink.getAttribute('href'));
  expect(response.status()).toBe(200);
  expect(response.headers()['content-type']).toBe('application/pdf');
  expect(response.headers()['content-disposition']).toBe('inline; filename="AA-4.pdf"');
  const download = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Télécharger Notice AA-4', exact: true }).click();
  expect((await download).suggestedFilename()).toBe('AA-4.pdf');
  await expect(page).toHaveURL(/\/documents\/\?reference=AA-4/);
});

test('la recherche signale les expirations et permet de réinitialiser une recherche vide', async ({
  page,
}) => {
  await page.goto('/documents/?reference=BB-4');
  await expect(page.locator('.document-expired')).toBeVisible();
  await expect(
    page.getByRole('link', { name: 'Consulter Notice BB-4 (nouvel onglet)', exact: true }),
  ).toBeVisible();
  await page.getByLabel('Référence produit', { exact: true }).fill('introuvable');
  await page.getByRole('button', { name: 'Rechercher', exact: true }).click();
  await expect(page.getByText('Aucun document trouvé.', { exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'Réinitialiser', exact: true }).click();
  await expect(page.locator('.document-card')).toHaveCount(5);
  await expect(page.getByLabel('Référence produit', { exact: true })).toHaveValue('');
});
