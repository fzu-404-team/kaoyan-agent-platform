import { expect, test } from '@playwright/test'

const user = { id: 1, username: 'scores-test', role: 'STUDENT', status: 1 }
const row = { id: 1, year: 2026, college: '计算机与软件学院', majorCode: '085404', majorName: '计算机技术', examCombo: '11408',
  retestLine: 347, minScore: 347, medianScore: 367, avgScore: null, maxScore: 401, admittedCount: 29, flags: ['POSSIBLE_SAME_POOL'] }

test.beforeEach(async ({ page }) => {
  await page.addInitScript(u => {
    localStorage.setItem('token', 'test-token')
    localStorage.setItem('userInfo', JSON.stringify(u))
  }, user)
})

test('school detail shows user-provided score statistics with notice, flags and missing values', async ({ page }) => {
  await page.route('**/api/**', route => route.fulfill({ json: { code: 0, message: 'ok', data: {
    school: { id: 1, name: '测试大学', province: '广东', level: null }, details: [],
    scoreStatistics: [row, { ...row, id: 2, majorCode: null, majorName: '', retestLine: null, flags: ['MAX_BELOW_MEDIAN', 'FUTURE_FLAG'] }]
  } } }))
  await page.goto('/schools/1')
  await expect(page.getByRole('heading', { name: '往年录取分数统计' })).toBeVisible()
  await expect(page.getByText('非学校官网原文', { exact: false })).toBeVisible()
  await expect(page.getByText('可能与其他专业同一录取池', { exact: true })).toBeVisible()
  await expect(page.getByText('最高分低于中位分', { exact: true })).toBeVisible()
  await expect(page.getByText('数据待核对', { exact: true })).toBeVisible()
  await expect(page.getByText('专业名称未登记（代码未登记）', { exact: true })).toBeVisible()
  await expect(page.getByText('未登记', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('POSSIBLE_SAME_POOL')).toHaveCount(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false)
  await page.screenshot({ path: test.info().outputPath('school-scores.png'), fullPage: true })
})

test('older detail responses without scoreStatistics keep the original page', async ({ page }) => {
  await page.route('**/api/**', route => route.fulfill({ json: { code: 0, message: 'ok', data: {
    school: { id: 1, name: '旧版院校', province: '江苏', level: '211' }, details: []
  } } }))
  await page.goto('/schools/1')
  await expect(page.getByRole('heading', { name: '旧版院校', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '往年录取分数统计' })).toHaveCount(0)
})

test('empty statistics list says so without inventing values', async ({ page }) => {
  await page.route('**/api/**', route => route.fulfill({ json: { code: 0, message: 'ok', data: {
    school: { id: 1, name: '空统计院校', province: '江苏', level: null }, details: [], scoreStatistics: []
  } } }))
  await page.goto('/schools/1')
  await expect(page.getByText('该院校暂无录取分数统计')).toBeVisible()
})
