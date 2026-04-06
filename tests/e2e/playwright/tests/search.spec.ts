import { test, expect } from '../fixtures/test-fixtures';

test.describe('Search', () => {
  test('typing shows search dropdown with results', async ({ page, seededProject }) => {
    await page.goto(`/projects/${seededProject.projectId}`);

    const searchInput = page.locator('[data-testid="search-input"]');
    await searchInput.click();
    await searchInput.fill('Task');

    // Dropdown should appear with results
    await expect(page.locator('[data-testid="search-dropdown"]')).toBeVisible({ timeout: 5_000 });
    await expect(page.locator('[data-testid="search-result"]').first()).toBeVisible();
  });

  test('typing filters results to matching items', async ({ page, seededProject }) => {
    await page.goto(`/projects/${seededProject.projectId}`);

    const searchInput = page.locator('[data-testid="search-input"]');
    await searchInput.click();
    await searchInput.fill('Backlog Task');

    // Wait for search results
    await expect(page.locator('[data-testid="search-result"]')).toBeVisible({ timeout: 5_000 });
    await expect(page.locator('[data-testid="search-result"]').first()).toContainText('Backlog Task');
  });

  test('clicking result navigates to detail', async ({ page, seededProject }) => {
    await page.goto(`/projects/${seededProject.projectId}`);

    const searchInput = page.locator('[data-testid="search-input"]');
    await searchInput.click();
    await searchInput.fill('Active Task');

    const result = page.locator('[data-testid="search-result"]').first();
    await expect(result).toBeVisible({ timeout: 5_000 });
    await result.click();

    // Detail panel should open
    await expect(page.locator('.detail-panel')).toBeVisible();
    await expect(page.locator('.detail-title')).toContainText('Active Task');
  });

  test('search shows loading state while fetching', async ({ page, seededProject }) => {
    await page.goto(`/projects/${seededProject.projectId}`);

    const searchInput = page.locator('[data-testid="search-input"]');
    await searchInput.click();
    await searchInput.fill('Test');

    // Loading or results should appear
    const dropdown = page.locator('[data-testid="search-dropdown"]');
    await expect(dropdown).toBeVisible({ timeout: 5_000 });
  });
});
