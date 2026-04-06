import { test, expect } from '../fixtures/test-fixtures';

test.describe('Board View', () => {
  test('renders all board columns', async ({ page, seededProject }) => {
    await page.goto(`/projects/${seededProject.projectId}`);
    await expect(page.locator('.column-title', { hasText: 'In Progress' })).toBeVisible();
    await expect(page.locator('.column-title', { hasText: 'Review' })).toBeVisible();
    await expect(page.locator('.column-title', { hasText: 'Done' })).toBeVisible();
    // Backlog is a separate section
    await expect(page.locator('.board-backlog')).toBeVisible();
  });

  test('tasks appear in correct columns', async ({ page, seededProject }) => {
    await page.goto(`/projects/${seededProject.projectId}`);

    // Backlog task should be in the backlog tree
    await expect(page.locator('.backlog-task', { hasText: 'Backlog Task' })).toBeVisible();

    // Active task should be in the In Progress column
    const inProgressCol = page.locator('.column').filter({ has: page.locator('.column-title', { hasText: 'In Progress' }) });
    await expect(inProgressCol.locator('.task-card', { hasText: 'Active Task' })).toBeVisible();

    // Done task should be in the Done column (may need archive toggle)
    const doneCol = page.locator('.column').filter({ has: page.locator('.column-title', { hasText: 'Done' }) });
    await expect(doneCol.locator('.task-card', { hasText: 'Completed Task' })).toBeVisible();
  });

  test('task cards show entity number and title', async ({ page, seededProject }) => {
    await page.goto(`/projects/${seededProject.projectId}`);
    const activeTask = seededProject.tasks.find(t => t.status === 'in_progress')!;
    const card = page.locator('.task-card', { hasText: 'Active Task' });
    await expect(card).toBeVisible();
    await expect(card.locator('.entity-number')).toHaveText(`T-${activeTask.number}`);
  });

  test('task cards show breadcrumb pills', async ({ page, seededProject }) => {
    await page.goto(`/projects/${seededProject.projectId}`);
    const card = page.locator('.task-card', { hasText: 'Active Task' });
    await expect(card.locator('.breadcrumb-pills')).toBeVisible();
    // Should show epic and feature pills
    await expect(card.locator('.pill')).toHaveCount(2);
  });

  test('clicking task card opens detail panel', async ({ page, seededProject }) => {
    await page.goto(`/projects/${seededProject.projectId}`);
    const activeTask = seededProject.tasks.find(t => t.status === 'in_progress')!;
    await page.locator('.task-card', { hasText: 'Active Task' }).click();
    await expect(page.locator('.detail-panel')).toBeVisible();
    await expect(page).toHaveURL(new RegExp(`/tasks/${activeTask.id}`));
  });

  test('archive toggle in done column', async ({ page, seededProject, api }) => {
    await page.goto(`/projects/${seededProject.projectId}`);
    const doneCol = page.locator('.column').filter({ has: page.locator('.column-title', { hasText: 'Done' }) });

    // The completed task should be visible
    await expect(doneCol.locator('.task-card', { hasText: 'Completed Task' })).toBeVisible();

    // Click archive button if it exists
    const archiveBtn = doneCol.locator('.archive-btn');
    if (await archiveBtn.isVisible()) {
      await archiveBtn.click();
      // Task should now be archived (hidden from main list)
      await expect(doneCol.locator('.task-card', { hasText: 'Completed Task' })).not.toBeVisible();

      // Toggle archived section to reveal it
      const archivedToggle = doneCol.locator('.archived-toggle');
      await archivedToggle.click();
      await expect(doneCol.locator('.archived-task', { hasText: 'Completed Task' })).toBeVisible();
    }
  });
});
