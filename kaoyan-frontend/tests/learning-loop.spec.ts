import { test, expect } from '@playwright/test'
import type { ManagedItem } from '../src/api/learning'

const item = (id: number): ManagedItem => ({ itemId: id, questionId: id, orderIndex: id - 1, subject: '数据结构', knowledgePoint: '树', difficulty: 'EASY',
  content: `诊断题${id}`, optionA: '选择甲', optionB: '选择乙', optionC: '选择丙', optionD: '选择丁', userAnswer: null,
  draftAnswer: null, submitted: false, hintLevelUsed: 0, withdrawn: false, isCorrect: null, answer: null, analysis: null })

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('token', 'test-learning-token')
    localStorage.setItem('userInfo', JSON.stringify({ id: 1, username: 'learning-test', role: 'STUDENT', status: 1 }))
  })
})

test('diagnostic draft survives refresh and grading waits for finish', async ({ page }) => {
  const state = { sessionId: 'L-diagnostic-test', kind: 'DIAGNOSTIC', state: 'RUNNING', revision: 0, currentIndex: 0,
    blueprint: { id: 'prototype', missing: [{ subject: '操作系统', difficulty: 'HARD', missing: 1 }] }, items: [item(1), item(2)] }
  let submits = 0
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    let data: unknown = []
    if (path.endsWith('/state')) data = state
    else if (path.endsWith('/progress')) {
      const body = route.request().postDataJSON(); expect(body.revision).toBe(state.revision)
      for (const [key, value] of Object.entries<string>(body.answers)) state.items.find(i => i.itemId === Number(key))!.draftAnswer = value
      state.revision++; state.currentIndex = body.currentIndex; data = state
    } else if (path.endsWith('/answer')) {
      const body = route.request().postDataJSON(); expect(body.clientRequestId).toBeTruthy(); expect(body.itemId).toBe(1)
      submits++; state.items[0].submitted = true; state.items[0].userAnswer = body.answer; state.items[0].draftAnswer = null; state.revision++
      data = { submitted: true, isCorrect: null, answer: null }
    } else if (path.endsWith('/finish') || path.endsWith('/result')) {
      state.state = 'FINISHED'; state.items[0].isCorrect = 1; state.items[0].answer = 'B'; state.items[0].analysis = '结束后保存的解析'
      data = { session: state, answered: 1, correct: 1, unanswered: 1, withdrawn: 0, accuracy: 1, independentAccuracy: 1,
        assisted: 0, diagnosticReferenceScore: null, notice: '局部诊断不输出完整参考分', profilePending: true }
    }
    await route.fulfill({ json: { code: 0, message: 'ok', data } })
  })
  await page.goto('/practice/session/L-diagnostic-test')
  await page.getByText('B. 选择乙', { exact: true }).click()
  await expect(page.getByRole('status')).toContainText('已保存到服务端')
  await page.reload()
  await expect(page.getByRole('radio', { name: 'B. 选择乙' })).toBeChecked()
  await page.getByRole('button', { name: '提交本题' }).click()
  await expect(page.getByText('已提交：B')).toBeVisible()
  await expect(page.getByRole('button', { name: '第 1 题，已提交，待公布判分' })).toHaveClass(/el-button--info/)
  await expect(page.getByRole('button', { name: '第 2 题，未作答' })).toHaveClass(/el-button--info/)
  await expect(page.locator('.option-mark')).toHaveCount(0)
  await expect(page.getByText('标准答案：B')).toHaveCount(0)
  await expect(page.getByText('结束后保存的解析')).toHaveCount(0)
  await page.getByRole('button', { name: '结束批次并查看结果' }).click()
  await page.getByRole('button', { name: '确定', exact: true }).click()
  await expect(page.getByText('结束后保存的解析')).toBeVisible()
  await expect(page.getByRole('button', { name: '第 1 题，答对' })).toHaveClass(/el-button--success/)
  await expect(page.getByText('局部诊断不输出完整参考分')).toBeVisible()
  expect(submits).toBe(1)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

test('practice history preserves each question grade and marks the selected wrong answer', async ({ page }) => {
  const sessionId = 'L-mixed-history'
  const state = {
    sessionId, kind: 'PRACTICE', state: 'FINISHED', revision: 4, currentIndex: 0,
    blueprint: { id: 'practice-v1' },
    items: [
      { ...item(1), submitted: true, userAnswer: 'B', isCorrect: 1, answer: 'B' },
      { ...item(2), submitted: true, userAnswer: 'A', isCorrect: 0, answer: 'B' },
      item(3),
      { ...item(4), submitted: true, userAnswer: 'A', withdrawn: true }
    ]
  }
  const result = {
    session: state, total: 4, answered: 2, correct: 1, unanswered: 1, withdrawn: 1,
    accuracy: 0.5, independentAccuracy: 0.5, assisted: 0
  }
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    let data: unknown = []
    if (path === '/api/practice/sessions/page') {
      data = { total: 1, list: [{ sessionId, total: 4, answered: 2, correct: 1, accuracy: 50 }] }
    } else if (path === `/api/practice/sessions/${sessionId}/state`) {
      data = state
    } else if (path === `/api/practice/sessions/${sessionId}/result`) {
      data = result
    }
    await route.fulfill({ json: { code: 0, data } })
  })

  const openHistory = () => page.getByRole('button', { name: '查看详情' }).click()
  const correct = page.getByRole('button', { name: '第 1 题，答对' })
  const wrong = page.getByRole('button', { name: '第 2 题，答错' })
  const unanswered = page.getByRole('button', { name: '第 3 题，未作答' })
  const withdrawn = page.getByRole('button', { name: '第 4 题，已撤回' })
  const expectColors = async () => {
    await expect(correct).toHaveClass(/el-button--success/)
    await expect(wrong).toHaveClass(/el-button--danger/)
    await expect(unanswered).toHaveClass(/el-button--info/)
    await expect(withdrawn).toHaveClass(/el-button--info/)
  }

  await page.goto('/practice')
  await openHistory()
  await expectColors()
  await expect(correct).toHaveAttribute('aria-current', 'step')
  await wrong.click()
  await expect(wrong).toHaveAttribute('aria-current', 'step')
  await expect(wrong).toHaveCSS('outline-offset', '2px')
  await expect(correct).not.toHaveAttribute('aria-current', 'step')
  await expectColors()
  await expect(page.getByRole('radio', { name: /A\. 选择甲.*你的选择/ })).toBeChecked()
  await expect(page.getByRole('radio', { name: /B\. 选择乙.*正确答案/ })).toBeVisible()

  await unanswered.click()
  await expect(page.locator('.option-mark')).toHaveCount(0)
  await withdrawn.click()
  await expect(page.getByText('该版本已撤回，不参与作答与有效统计。')).toBeVisible()
  await page.goto('/practice')
  await openHistory()
  await expectColors()
  await wrong.click()
  await expect(page.getByRole('radio', { name: /A\. 选择甲.*你的选择/ })).toBeChecked()
})

test('draft version conflict requires explicit reload and never displays saved', async ({ page }) => {
  const state = { sessionId: 'L-conflict', kind: 'PRACTICE', state: 'RUNNING', revision: 0, currentIndex: 0, blueprint: { id: 'v1' }, items: [item(1)] }
  await page.route('**/api/**', async route => {
    if (new URL(route.request().url()).pathname.endsWith('/progress')) return route.fulfill({ status: 409, json: { code: 409, message: '草稿版本已变化', data: null } })
    await route.fulfill({ json: { code: 0, message: 'ok', data: state } })
  })
  await page.goto('/practice/session/L-conflict')
  await page.getByText('A. 选择甲', { exact: true }).click()
  await expect(page.getByText('尚未保存', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '提交本题' })).toBeDisabled()
  await page.getByRole('button', { name: '重新读取服务端进度' }).click()
  await expect(page.getByRole('radio', { name: 'A. 选择甲' })).not.toBeChecked()
})
