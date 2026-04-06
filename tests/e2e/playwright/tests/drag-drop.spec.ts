import { test, expect } from '../fixtures/test-fixtures';

test.describe('Drag and Drop', () => {
  test.slow(); // Drag tests are inherently slower

  async function dragElement(
    page: import('@playwright/test').Page,
    source: import('@playwright/test').Locator,
    target: import('@playwright/test').Locator,
  ) {
    // Force drag handles visible
    await page.addStyleTag({ content: '.drag-handle { opacity: 1 !important; }' });
    await page.waitForTimeout(100);

    const sourceBox = await source.boundingBox();
    const targetBox = await target.boundingBox();
    if (!sourceBox || !targetBox) throw new Error('Could not get bounding boxes');

    const startX = sourceBox.x + sourceBox.width / 2;
    const startY = sourceBox.y + sourceBox.height / 2;
    const endX = targetBox.x + targetBox.width / 2;
    // Aim above the target to drop before it
    const endY = targetBox.y + 2;

    await page.mouse.move(startX, startY);
    await page.mouse.down();

    // Move slowly in 20 steps to exceed the 5px activation distance
    const steps = 20;
    for (let i = 1; i <= steps; i++) {
      const x = startX + ((endX - startX) * i) / steps;
      const y = startY + ((endY - startY) * i) / steps;
      await page.mouse.move(x, y);
      await page.waitForTimeout(30);
    }

    await page.waitForTimeout(300);
    await page.mouse.up();
    await page.waitForTimeout(500);
  }

  test('reorder epics in backlog', async ({ page, seededProject, api }) => {
    // Create a second epic
    const epic2 = await api.createEpic(seededProject.projectId, 'Second Epic', seededProject.apiKey);
    await api.createFeature(seededProject.projectId, epic2.id, 'Second Feature', seededProject.apiKey);

    await page.goto(`/projects/${seededProject.projectId}`);
    await expect(page.locator('.backlog-epic')).toHaveCount(2);

    // Verify initial order
    await expect(page.locator('.backlog-epic').nth(0).locator('.backlog-epic-title')).toContainText('Test Epic');
    await expect(page.locator('.backlog-epic').nth(1).locator('.backlog-epic-title')).toContainText('Second Epic');

    // The drag handles have aria-roledescription="sortable" and aria-label="Reorder"
    // Epic-level drag handles are direct children of the SortableItem wrapper (parent of .backlog-epic)
    // Use CSS child combinator to get only the immediate drag handle, not nested ones
    const secondEpicParent = page.locator('.backlog-epic').nth(1).locator('..');
    const secondHandle = secondEpicParent.locator('> .drag-handle');
    const firstEpicParent = page.locator('.backlog-epic').nth(0).locator('..');

    await dragElement(page, secondHandle, firstEpicParent);

    // Check order is swapped
    await expect(page.locator('.backlog-epic').nth(0).locator('.backlog-epic-title')).toContainText('Second Epic');
  });

  test('order persists after refresh', async ({ page, seededProject, api }) => {
    // Create second epic
    const epic2 = await api.createEpic(seededProject.projectId, 'Persistent Epic', seededProject.apiKey);
    await api.createFeature(seededProject.projectId, epic2.id, 'Persistent Feature', seededProject.apiKey);

    await page.goto(`/projects/${seededProject.projectId}`);
    await expect(page.locator('.backlog-epic')).toHaveCount(2);
    await expect(page.locator('.backlog-epic').nth(0).locator('.backlog-epic-title')).toContainText('Test Epic');

    const secondEpicParent = page.locator('.backlog-epic').nth(1).locator('..');
    const secondHandle = secondEpicParent.locator('> .drag-handle');
    const firstEpicParent = page.locator('.backlog-epic').nth(0).locator('..');

    await dragElement(page, secondHandle, firstEpicParent);

    await expect(page.locator('.backlog-epic').nth(0).locator('.backlog-epic-title')).toContainText('Persistent Epic');

    // Refresh and verify order persists
    await page.reload();
    await expect(page.locator('.backlog-epic')).toHaveCount(2);
    await expect(page.locator('.backlog-epic').nth(0).locator('.backlog-epic-title')).toContainText('Persistent Epic');
  });
});
