import { expect, test, type Page } from '@playwright/test'

const user = { id: 1, username: 'g11-test', role: 'STUDENT', status: 1 }

async function login(page: Page) {
  await page.addInitScript(u => {
    localStorage.setItem('token', 'g11-token')
    localStorage.setItem('userInfo', JSON.stringify(u))
  }, user)
}

test('default start button stays in the first screen and the answer loop completes', async ({ page }, testInfo) => {
  await login(page)
  const question = {
    id: 1, content: 'G11 移动端闭环测试题', subject: '数据结构', difficulty: 'MEDIUM',
    optionA: '选项甲', optionB: '选项乙', optionC: '选项丙', optionD: '选项丁'
  }
  await page.route('http://127.0.0.1:4173/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    let data: unknown
    if (path === '/api/learning/status') data = { enabled: true }
    else if (path === '/api/learning/profile') data = { independentSamples: 0 }
    else if (path === '/api/practice/sessions/page') data = { total: 0, list: [] }
    else if (path === '/api/practice/sessions' && route.request().method() === 'POST') {
      expect(route.request().postDataJSON()).toMatchObject({ subject: '数据结构', difficulty: 'MEDIUM', count: 5, source: 'NORMAL' })
      data = { sessionId: 'g11-session' }
    } else if (path === '/api/practice/sessions/g11-session/answer') {
      expect(route.request().postDataJSON()).toEqual({ questionId: 1, answer: 'B' })
      data = { recordId: 9, questionId: 1, userAnswer: 'B', isCorrect: 0, answer: 'C', analysis: 'G11 服务器解析' }
    } else if (path === '/api/practice/sessions/g11-session') data = [{ questionId: 1, orderIndex: 0, isCorrect: null }]
    else if (path === '/api/questions/1') data = question
    else data = null
    await route.fulfill({ json: { code: 0, message: 'ok', data } })
  })
  await page.goto('/practice')
  const start = page.getByRole('button', { name: '开始刷题', exact: true })
  await expect(start).toBeVisible()
  await expect(page.locator('.cfg-summary')).toHaveText('将从 普通练习 · 数据结构 · 中等 · 5 题 中抽题')
  // 首屏可见：默认配置下按钮完整落在视口内，无需滚动
  expect(await start.evaluate(el => {
    const box = el.getBoundingClientRect()
    return box.top >= 0 && box.bottom <= window.innerHeight
  })).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('practice-home.png') })

  await start.click()
  await page.waitForURL('**/practice/session/g11-session')
  await page.getByText('选项乙', { exact: true }).click()
  await expect(page.getByRole('status').filter({ hasText: '已选择 B' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.getByRole('button', { name: '提交答案', exact: true }).click()
  const feedback = page.locator('.feedback')
  await expect(feedback).toContainText('回答错误，正确答案：C')
  await expect(feedback).toContainText('G11 服务器解析')
  // 提交后反馈自动滚入视野，手机上不用手动找判分结果
  await expect.poll(() => feedback.evaluate(el => {
    const box = el.getBoundingClientRect()
    return box.top >= 0 && box.bottom <= window.innerHeight
  })).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('practice-feedback.png') })
  await page.getByRole('button', { name: '完成，查看结果', exact: true }).click()
  await expect(page.locator('.el-result__title')).toHaveText('本次练习完成')
})

test('school detail keeps priority fields readable on phones and the full table on desktop', async ({ page }, testInfo) => {
  await login(page)
  const source = { title: '招生计划原文', url: 'https://example.edu.cn/plan', locator: '计算机学院专业合计', retrievedAt: '2026-10-30', sourceType: 'OFFICIAL' }
  const enrollment = { year: 2027, value: 77, status: 'OFFICIAL', scopeKey: 'same-plan', scopeLabel: '专业合计，各方向共用，勿累加', basis: 'TOTAL_INCLUDING_RECOMMENDED', notice: '暂定计划', sources: [source] }
  const cutoffReference = { year: 2026, value: 310, status: 'UNVERIFIED', scopeKey: 'history', scopeLabel: '普通全日制', basis: 'NOT_APPLICABLE', notice: '第三方数据待核实', sources: [{ ...source, sourceType: 'THIRD_PARTY', title: '历史线登记', url: 'https://example.org/cutoff' }] }
  const remark = '【官方招生事实】计算机学院全日制统考方向，备注较长需要完整阅读：复试含机试与面试，同等学力需加试两门本科主干课程。'
  const details = [
    {
      id: 10, schoolId: 1, majorName: '计算机科学与技术', majorCode: '081200', year: 2027,
      enrollmentCount: null, scoreLine: null, remark,
      admissionMetrics: { college: '计算机学院', track: '01计算机系统', studyMode: 'full_time', admissionCategory: 'ordinary', enrollment, cutoffReference }
    },
    { id: 11, schoolId: 1, majorName: '计算机技术', majorCode: '085404', year: 2025, enrollmentCount: 40, scoreLine: 300, remark: '旧版登记备注' }
  ]
  await page.route('http://127.0.0.1:4173/api/**', route => route.fulfill({
    json: { code: 0, message: 'ok', data: { school: { id: 1, name: 'G11 测试院校', province: '河北', level: '211' }, details } }
  }))
  await page.goto('/schools/1')
  await expect(page.getByRole('heading', { name: 'G11 测试院校', exact: true })).toBeVisible()

  if (testInfo.project.name === 'mobile') {
    const cards = page.locator('.major-card')
    await expect(cards).toHaveCount(2)
    await expect(page.locator('.el-table')).toHaveCount(0)
    const first = cards.first()
    await expect(first.locator('.major-name')).toHaveText('计算机科学与技术')
    await expect(first.getByText('2027年', { exact: true })).toBeVisible()
    const cutoff = first.getByText('2026年 复试参考线：310分', { exact: true })
    await expect(first.getByText('2027年 招生计划：77人', { exact: true })).toBeVisible()
    await expect(cutoff).toBeVisible()
    // 四个优先字段不展开就能在首屏读完
    expect(await cutoff.evaluate(el => el.getBoundingClientRect().bottom <= window.innerHeight)).toBe(true)
    // 其余字段默认折叠，展开后能读完一条完整专业记录
    await expect(first.getByText(remark, { exact: true })).toBeHidden()
    await first.locator('.major-more summary').click()
    await expect(first.getByText(remark, { exact: true })).toBeVisible()
    await expect(first.getByText('081200', { exact: true })).toBeVisible()
    await expect(first.getByText('计算机学院', { exact: true })).toBeVisible()
    await expect(first.getByText('01计算机系统', { exact: true })).toBeVisible()
    await expect(first.getByText('全日制', { exact: true })).toBeVisible()
    await expect(first.getByText('普通统考', { exact: true })).toBeVisible()
    await expect(cards.nth(1).getByText('2025年原登记：40人', { exact: true })).toBeVisible()
    await expect(cards.nth(1).getByText('2025年原登记：300分', { exact: true })).toBeVisible()
  } else {
    await expect(page.locator('.el-table')).toBeVisible()
    await expect(page.locator('.major-card')).toHaveCount(0)
    for (const label of ['专业', '专业代码', '年份', '学院／方向', '招生计划与口径', '往年复试参考线', '备注']) {
      await expect(page.getByRole('columnheader', { name: label, exact: true })).toBeVisible()
    }
    await expect(page.getByText('2027年 招生计划：77人', { exact: true })).toBeVisible()
    await expect(page.getByText('2026年 复试参考线：310分', { exact: true })).toBeVisible()
    await expect(page.getByText(remark, { exact: true })).toBeVisible()
    await expect(page.getByText('2025年原登记：40人', { exact: true })).toBeVisible()
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('school-detail.png'), fullPage: true })
})