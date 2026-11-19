import request from './request'
import type { School, SchoolDetail, SchoolWarning, ScoreStatistic } from '@/types/api'

export interface SchoolDetailVO {
  school: School
  details: SchoolDetail[]
  warnings?: SchoolWarning[]
  scoreStatistics?: ScoreStatistic[]
}

export interface SchoolOptions {
  provinces: string[]
  majorNames: string[]
}

export const getSchoolOptions = () =>
  request.get<unknown, SchoolOptions>('/schools/options')

export const searchSchools = (params: {
  province?: string
  level?: string
  majorName?: string
}) => request.get<unknown, School[]>('/schools', { params })

export const getSchoolDetail = (schoolId: number, signal?: AbortSignal) =>
  request.get<unknown, SchoolDetailVO>(`/schools/${schoolId}`, { timeout: 15000, signal })
