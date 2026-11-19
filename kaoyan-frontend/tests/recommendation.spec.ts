import { test, expect } from '@playwright/test'

const user = {
  id: 1, username: 'browser-test', role: 'STUDENT', status: 1,
  examYear: 2027, targetMajor: '081200', targetSchool: '南京审计大学',
}
const schoolOptions = { provinces: ['北京', '江苏'], majorNames: ['计算机科学与技术', '计算机技术'] }
function task(outcome = 'COMPLETED') {
  return { id: 'browser-task', taskType: 'SCHOOL_RECOMMEND', userId: 1, status: 'SUCCESS', createdAt: '2026-10-14T12:00:00',
    releaseId: 'rag-v1-1234567890abcdef', resultPayload: { outcome, answer: outcome === 'COMPLETED'
      ? '满足条件的候选清单\n院校目录中有 18 条登记匹配本轮条件，展示 1 所。\n- 重庆大学 · 旧版重复目录正文'
      : '当前资料没有符合条件的候选',
      explanationMode: 'rules', releaseId: 'rag-v1-1234567890abcdef', references: outcome === 'COMPLETED' ? [{ id: 'nau', title: '官方目录',
        url: 'https://gs.nau.edu.cn/2026/0920/c4397a161925/page.htm', locator: '计算机学院', version: 'admissions-2027-v1', retrievedAt: '2026-10-14', excerpt: '目录摘要' }] : [],
      candidates: outcome === 'COMPLETED' ? [{ programId: 'nau-2027-081200', school: '南京审计大学', college: '计算机学院', year: 2027,
        major: '计算机科学与技术', majorCode: '081200', degreeType: 'academic', region: '江苏', studyMode: 'full_time', examSubjects: ['101','201','301','408'],
        matchedConditions: ['年份一致'], pendingChecks: ['资格需确认'], sourceIds: ['nau'],
        citationSupport: { status: 'SUPPORTED' }, explanation: '<img src=x onerror=alert(1)>' }] : [],
      unverifiedCandidates: outcome === 'COMPLETED' ? [{
        programId: 'cqu-2027-081200', school: '重庆大学', college: '计算机学院', year: 2027, major: '计算机科学与技术',
        majorCode: '081200', degreeType: 'academic', region: '重庆', studyMode: 'full_time', examSubjects: ['101','201','301','408'],
        catalogReview: 'USER_APPROVED',
      }] : [],
      scoreReferences: outcome === 'COMPLETED' ? [{ programId: 'nau-2027-081200', year: 2026, retestLine: 320, examCombo: '11408', gap: 15 }] : [],
    } }
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(u => { localStorage.setItem('token', 'test-token'); localStorage.setItem('userInfo', JSON.stringify(u)) }, user)
})

test('recommendation, safe rendering, sources and saved history', async ({ page }) => {
  let saved: ReturnType<typeof task>[] = []
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url())
    let data: unknown = []
    if (url.pathname.endsWith('/schools/options')) data = schoolOptions
    else if (url.pathname.endsWith('/users/me')) data = user
    else if (url.pathname.endsWith('/recommends/generate')) {
      const body = route.request().postDataJSON()
      expect(body.preferences.explainWithAi).toBe(false)
      expect(body.mockScore).toEqual({ total: 335, examCombo: '11408' })
      expect(body.profile).toBeUndefined()
      saved = [task()]; data = saved[0]
    } else if (url.pathname.endsWith('/recommends')) data = saved
    await route.fulfill({ json: { code: 0, message: 'ok', data } })
  })
  await page.goto('/schools')
  await expect(page.getByRole('heading', { name: '院校与专业' })).toBeVisible()
  await page.goto('/school-recommendations')
  await expect(page.locator('.el-menu-item.is-active')).toContainText('择校推荐')
  await expect(page.getByText('意向院校 南京审计大学', { exact: false })).toBeVisible()
  await page.getByText('按模考总分推荐（冲／稳／保）', { exact: true }).click()
  await page.getByLabel('模考总分', { exact: true }).fill('335')
  await page.getByText('选择与模考一致的组合', { exact: true }).click()
  await page.getByRole('option', { name: '政治 / 英语一 / 数学一 / 408' }).click()
  await page.getByRole('button', { name: '生成推荐', exact: true }).click()
  const result = page.locator('.result-pane')
  await expect(result.getByRole('heading', { name: '南京审计大学' })).toBeVisible()
  await expect(result.locator('.score')).toContainText('2026 年参考复试线 320 分')
  await expect(result.locator('.score')).toContainText('模考分差 +15 分')
  await expect(result.getByRole('heading', { name: '重庆大学' })).not.toBeVisible()
  await expect(result.getByRole('link', { name: '官方目录' })).not.toBeVisible()
  await page.screenshot({ path: test.info().outputPath('recommendation.png'), fullPage: true, animations: 'disabled' })
  await result.getByText('目录线索（1 项）', { exact: true }).click()
  await expect(result.getByRole('heading', { name: '重庆大学' })).toBeVisible()
  await expect(result.getByText('旧版重复目录正文', { exact: false })).toHaveCount(0)
  await result.getByText('查看依据（1）', { exact: true }).click()
  await expect(result.getByRole('link', { name: '官方目录' })).toHaveAttribute('href', /^https:\/\/gs.nau.edu.cn/)
  // Catalog clues also carry an evidence label in their own notes since 2026-11-19.
  await result.locator('.program').first().getByText('项目说明', { exact: true }).click()
  await expect(result.locator('.program img')).toHaveCount(0)
  await expect(result.getByText('<img src=x onerror=alert(1)>', { exact: true })).toBeVisible()
  await page.reload()
  await page.getByRole('tab', { name: '推荐历史' }).click()
  await page.getByRole('button', { name: '查看', exact: true }).click()
  await expect(page.getByRole('dialog').getByText('满足条件的候选清单')).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)
  expect(overflow).toBe(false)
})

test('score-based results show tiers, historical scores and the fixed data notice', async ({ page }) => {
  const notice = '按往年录取最低分／中位分分层，数据为用户提供并经用户审核批准，非学校官网原文；公布录取数可能为共用录取池；往年分数不代表今年分数线，分层不代表录取概率。'
  const program = (id: string, school: string, tier: string, min: number, median: number, gap: number) => ({
    programId: id, school, college: '计算机学院', year: 2026, major: '计算机科学与技术', majorCode: '081200',
    degreeType: 'academic', region: '上海', studyMode: 'unknown', examSubjects: ['101', '201', '301', '408'],
    matchedConditions: ['专业一致'], pendingChecks: [], sourceIds: [], explanation: '规则说明', evidenceLevel: 'SCORE_HISTORY',
    scoreMatch: { ruleVersion: 'score-match-v1', tier, statYear: 2026, college: '计算机学院', examCombo: '11408',
      minScore: min, medianScore: median, gapToMin: gap },
  })
  const scored = { id: 'score-task', taskType: 'SCHOOL_RECOMMEND', userId: 1, status: 'SUCCESS', createdAt: '2026-11-19T01:00:00',
    releaseId: 'rag-v1-1234567890abcdef', resultPayload: {
      outcome: 'COMPLETED', answer: '按往年录取最低分／中位分（英语一＋数学一＋408）分层：冲刺1所、保底1所。另有2所低于往年范围、0所缺可比分数、0所科目组合不符或未登记，未列入。',
      explanationMode: 'rules', releaseId: 'rag-v1-1234567890abcdef', references: [],
      candidates: [program('reach', '冲刺样例大学', 'REACH', 330, 350, -10), program('safe', '保底样例大学', 'SAFE', 280, 300, 40)],
      unverifiedCandidates: [],
      scoreFilter: { ruleVersion: 'score-match-v1', examCombo: '11408', notice,
        counts: { comparable: 2, below: 2, noData: 0, comboMismatch: 0 } },
    } }
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    const data = path.endsWith('/schools/options') ? schoolOptions : path.endsWith('/users/me') ? user : path.endsWith('/recommends/generate') ? scored : []
    await route.fulfill({ json: { code: 0, message: 'ok', data } })
  })
  await page.goto('/school-recommendations')
  await page.getByRole('button', { name: '生成推荐', exact: true }).click()
  const result = page.locator('.result-pane')
  await expect(result.locator('.program').first().locator('.tier')).toHaveText('冲')
  await expect(result.locator('.program').nth(1).locator('.tier')).toHaveText('保')
  await expect(result.locator('.program .score').first()).toHaveText('2026年录取最低330／中位350，差-10')
  await expect(result.locator('.program .score').nth(1)).toHaveText('2026年录取最低280／中位300，差+40')
  await expect(result.getByText(notice, { exact: true })).toBeVisible()
  await expect(result.getByText('另有2所低于往年范围', { exact: false })).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)
  expect(overflow).toBe(false)
})

test('no candidates remains an explicit outcome', async ({ page }) => {
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    const data = path.endsWith('/schools/options') ? schoolOptions : path.endsWith('/users/me') ? user : path.endsWith('/recommends/generate') ? task('UNSUPPORTED') : []
    await route.fulfill({ json: { code: 0, message: 'ok', data } })
  })
  await page.goto('/school-recommendations')
  await page.getByRole('button', { name: '生成推荐', exact: true }).click()
  await expect(page.getByText('资料未覆盖', { exact: true })).toBeVisible()
  await expect(page.locator('.program')).toHaveCount(0)
})

test('late unauthorized response cannot log out a newer account', async ({ page }) => {
  let started = false
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/recommends/generate')) {
      started = true
      await gate
      await route.fulfill({ status: 401, json: { code: 401, message: 'old account expired' } })
    } else await route.fulfill({ json: { code: 0, message: 'ok', data: path.endsWith('/schools/options') ? schoolOptions : path.endsWith('/users/me') ? user : [] } })
  })
  await page.goto('/school-recommendations')
  await page.getByRole('button', { name: '生成推荐', exact: true }).click()
  await expect.poll(() => started).toBe(true)
  await page.evaluate(() => {
    const app = (document.querySelector('#app') as any).__vue_app__
    const store = app.config.globalProperties.$pinia._s.get('user')
    store.token = 'new-account-token'
    store.setUserInfo({ id: 2, username: 'new-account', role: 'STUDENT', status: 1 })
    localStorage.setItem('token', 'new-account-token')
  })
  const response = page.waitForResponse(r => r.url().endsWith('/recommends/generate') && r.status() === 401)
  release()
  await response
  await expect(page.locator('.uname')).toHaveText('new-account')
  expect(await page.evaluate(() => localStorage.getItem('token'))).toBe('new-account-token')
  await expect(page.locator('.program')).toHaveCount(0)
})

test('automatic settings and last saved task are only loaded on the new recommendation page', async ({ page }) => {
  let settingsReads = 0
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    let data: unknown = []
    if (path.endsWith('/learning/status')) data = { enabled: true }
    else if (path.endsWith('/users/me')) data = user
    else if (path.endsWith('/schools/options')) data = schoolOptions
    else if (path.endsWith('/recommendation-settings')) {
      if (route.request().method() === 'GET') settingsReads++
      else expect(route.request().postDataJSON()).toMatchObject({ revision: 3, enabled: false })
      data = { revision: 3, enabled: route.request().method() === 'GET', preferences: {},
        status: 'CURRENT', lastTaskId: 'browser-task', profileRevision: 14, updatedAt: '2026-11-18T23:10:19' }
    } else if (path.endsWith('/tasks/browser-task')) data = task()
    await route.fulfill({ json: { code: 0, message: 'ok', data } })
  })
  await page.goto('/schools')
  await expect(page.getByRole('heading', { name: '院校与专业' })).toBeVisible()
  expect(settingsReads).toBe(0)
  await page.goto('/school-recommendations')
  await page.getByRole('tab', { name: '自动更新' }).click()
  await expect(page.getByRole('heading', { name: '南京审计大学' })).toBeVisible()
  const status = page.getByRole('tabpanel', { name: '自动更新' }).getByRole('status')
  await expect(status).toHaveText(/已更新\s*· 上次生成 2026-11-18 23:10/)
  expect(settingsReads).toBe(1)
  await status.locator('..').locator('.el-switch__core').click()
  await page.getByRole('button', { name: '保存推荐设置' }).click()
  await expect(status).toContainText('自动更新未启用')
})
