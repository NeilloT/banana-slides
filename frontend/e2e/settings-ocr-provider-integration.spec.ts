import { expect, test, Page } from '@playwright/test'

function getOcrSection(page: Page) {
  return page.locator('h2').filter({ hasText: /OCR 配置|OCR Configuration/ }).locator('..')
}

test.afterAll(async ({ browser }) => {
  const page = await browser.newPage()
  await page.goto('/settings')
  await page.getByRole('button', { name: /重置|Reset/ }).click()
  await page.getByRole('button', { name: /确定重置|Confirm Reset/ }).click()
  await page.waitForTimeout(1000)
  await page.close()
})

test.describe('Settings: OCR provider integration (real backend)', () => {
  test.describe.configure({ mode: 'serial' })
  test.setTimeout(30_000)

  test('save Azure OCR provider config persists to backend', async ({ page }) => {
    await page.goto('/settings')

    const ocrSection = getOcrSection(page)
    const providerSelect = ocrSection.locator('select').first()
    await providerSelect.selectOption('azure')

    await ocrSection.getByPlaceholder(/https:\/\/<resource>\.cognitiveservices\.azure\.com/).fill(
      'https://integration-test.cognitiveservices.azure.com'
    )
    await ocrSection.getByPlaceholder(/Azure API Key/i).fill('azure-integration-secret')

    await page.getByRole('button', { name: /保存|Save/ }).click()
    await expect(page.locator('text=保存成功').or(page.locator('text=Settings saved successfully'))).toBeVisible({ timeout: 5000 })
  })

  test('reload shows persisted Azure OCR provider config', async ({ page }) => {
    await page.goto('/settings')

    const ocrSection = getOcrSection(page)
    const providerSelect = ocrSection.locator('select').first()
    await expect(providerSelect).toHaveValue('azure')

    const endpointInput = ocrSection.getByPlaceholder(/https:\/\/<resource>\.cognitiveservices\.azure\.com/)
    await expect(endpointInput).toHaveValue('https://integration-test.cognitiveservices.azure.com')

    const azureKeyInput = ocrSection.locator('input[type="password"]').last()
    await expect(azureKeyInput).toBeVisible()
    await expect(azureKeyInput).toHaveAttribute('placeholder', /length|长度/i)
  })
})
