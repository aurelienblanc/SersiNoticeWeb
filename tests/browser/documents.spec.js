const { test, expect } = require('playwright/test');

const productInput = (page) => page.getByRole('combobox', { name: 'Produit', exact: true });
const productOptions = (page) =>
  page.getByRole('listbox', { name: 'Produits disponibles' }).getByRole('option');
const chooseProduct = async (page, search, reference) => {
  await productInput(page).fill(search);
  await productOptions(page)
    .filter({ has: page.getByText(reference, { exact: true }) })
    .click();
};

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
  await productInput(page).fill('centrale');
  await expect(productOptions(page)).toHaveCount(2);
  await productInput(page).fill('aa-4');
  await expect(productOptions(page)).toHaveCount(2);
  await productOptions(page)
    .filter({ has: page.getByText('AA-4', { exact: true }) })
    .click();
  await page.getByRole('button', { name: 'Rechercher', exact: true }).click();
  await expect(page.locator('.document-card')).toHaveCount(1);
  await expect(page.locator('.document-card h3')).toHaveText('Notice AA-4');
  await expect(productInput(page)).toHaveValue('AA-4 · Centrale Alpha · Marque A');
  await expect(page).toHaveURL(/reference=AA-4/);
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

test('le type de document limite les résultats et se combine aux autres filtres', async ({
  page,
}) => {
  await page.goto('/documents/');
  const kind = page.getByLabel('Type de document', { exact: true });
  await kind.selectOption({ label: 'Certificat' });
  await page.getByRole('button', { name: 'Rechercher', exact: true }).click();
  await expect(page.locator('.document-card')).toHaveCount(1);
  await expect(page.locator('.document-kind')).toHaveText('Certificat');
  await expect(page.locator('.document-card h3')).toHaveText('Notice GEN');
  await expect(kind.locator('option:checked')).toHaveText('Certificat');
  await expect(page).toHaveURL(/type_document=\d+/);
  await page.getByLabel('Marque', { exact: true }).selectOption({ label: 'Marque A' });
  await chooseProduct(page, 'Alpha', 'AA-4');
  await page.getByRole('button', { name: 'Rechercher', exact: true }).click();
  await expect(page.getByText('Aucun document trouvé.', { exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'Réinitialiser', exact: true }).click();
  await expect(kind).toHaveValue('');
  await expect(page.locator('.document-card')).toHaveCount(5);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
});

test('la recherche signale les expirations et permet de réinitialiser une recherche vide', async ({
  page,
}) => {
  await page.goto('/documents/?reference=BB-4');
  await expect(page.locator('.document-expired')).toBeVisible();
  await expect(
    page.getByRole('link', { name: 'Consulter Notice BB-4 (nouvel onglet)', exact: true }),
  ).toBeVisible();
  await productInput(page).fill('introuvable');
  await expect(page.getByText('Aucun produit trouvé.', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Rechercher', exact: true }).click();
  await expect(page).toHaveURL(/reference=BB-4/);
  expect(await productInput(page).evaluate((input) => input.validationMessage)).toContain(
    'Choisissez un produit',
  );
  await productInput(page).fill('');
  await page.getByRole('button', { name: 'Rechercher', exact: true }).click();
  await expect(page.locator('.document-card')).toHaveCount(5);
  await page.getByRole('link', { name: 'Réinitialiser', exact: true }).click();
  await expect(page.locator('.document-card')).toHaveCount(5);
  await expect(productInput(page)).toHaveValue('');
});

test('le choix au clavier suit la marque et garde les produits inactifs accessibles', async ({
  page,
}) => {
  await page.goto('/documents/');
  const input = productInput(page);
  await input.fill('Centrale Alpha');
  await input.press('ArrowDown');
  await input.press('Enter');
  await expect(input).toHaveValue('AA-4 · Centrale Alpha · Marque A');
  await expect(input).toHaveAttribute('aria-expanded', 'false');
  await page.getByLabel('Marque', { exact: true }).selectOption({ label: 'Marque B' });
  await expect(input).toHaveValue('');
  await input.click();
  await expect(productOptions(page)).toHaveCount(2);
  await expect(
    productOptions(page).filter({ has: page.getByText('AA-4', { exact: true }) }),
  ).toHaveCount(0);
  await page.getByLabel('Marque', { exact: true }).selectOption({ label: 'Marque A' });
  await chooseProduct(page, 'Ancien', 'AA-OLD');
  await page.getByRole('button', { name: 'Rechercher', exact: true }).click();
  await expect(page.locator('.document-card h3')).toHaveText('Notice AA-OLD');
});

test('sans JavaScript le menu natif sélectionne aussi un produit exact', async ({
  browser,
  baseURL,
  viewport,
  isMobile,
}) => {
  const context = await browser.newContext({
    baseURL,
    viewport,
    isMobile,
    javaScriptEnabled: false,
  });
  try {
    const page = await context.newPage();
    await page.goto('/documents/');
    await page.getByLabel('Produit', { exact: true }).selectOption('AA-4');
    await page.getByRole('button', { name: 'Rechercher', exact: true }).click();
    await expect(page.locator('.document-card h3')).toHaveText('Notice AA-4');
    await expect(page.getByLabel('Produit', { exact: true })).toHaveValue('AA-4');
  } finally {
    await context.close();
  }
});
