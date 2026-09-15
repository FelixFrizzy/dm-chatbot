import { test, expect } from '@playwright/test';

test.use({
  storageState: 'dm-auth.json'
});

test('test', async ({ page }) => {
  await page.goto('https://www.dm.de/');
  await page.getByRole('navigation', { name: 'Haupt' }).getByRole('button').click();
  await page.getByRole('link', { name: 'Meine Einkäufe' }).click();
  await page.getByRole('link', { name: 'Bei Dir angekommen Am 11.07.' }).click();
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Rechnung anzeigen' }).click();
  const download = await downloadPromise;
});