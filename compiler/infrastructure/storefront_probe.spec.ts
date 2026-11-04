import { expect, test } from '@playwright/test';

test('The storefront renders and exposes its main navigation', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.stack ?? error.message));
  page.on('response', response => {
    const url = new URL(response.url());
    if (response.status() >= 400 && url.pathname.startsWith('/api/')) {
      errors.push(`${response.request().method()} ${url.pathname}: HTTP ${response.status()}`);
    }
  });
  try {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const navigation = page.getByRole('navigation', { name: 'Global navigation', exact: true });
    await expect(navigation).toBeVisible();
    const popular = page.getByRole('region', { name: 'Popular Products', exact: true });
    await expect(popular.getByText('Hummingbird detail t-shirt', { exact: true }).first()).toBeVisible();
  } catch (error) {
    const body = await page.locator('body').innerText({ timeout: 500 }).catch(() => '');
    throw new Error([
      ...errors.slice(0, 4).map(error => error.slice(0, 450)),
      `Visible page text: ${body.slice(0, 360) || '[empty]'}`,
      String(error),
    ].join('\n'));
  }
});
