<template>
  <div class="page schools-page">
    <div class="hero">
      <h1>院校与专业</h1><p>筛选院校，查看专业目录与招生资料</p>
      <div class="search-bar">
        <el-select v-model="q.province" placeholder="省份" aria-label="省份" filterable clearable :loading="optionsLoading" no-data-text="暂无选项">
          <el-option v-for="province in options.provinces" :key="province" :label="province" :value="province" />
        </el-select>
        <el-select v-model="q.level" placeholder="层次" aria-label="层次" clearable><el-option v-for="level in ['985','211','双一流','普通本科']" :key="level" :label="level" :value="level" /></el-select>
        <el-select v-model="q.majorName" placeholder="专业名" aria-label="专业名" filterable clearable :loading="optionsLoading" no-data-text="暂无选项">
          <el-option v-for="major in options.majorNames" :key="major" :label="major" :value="major" />
        </el-select>
        <el-button @click="load">搜索院校库</el-button>
      </div>
      <div v-if="optionsError" class="options-error" role="alert">
        筛选选项加载失败 <el-button size="small" :loading="optionsLoading" @click="loadOptions">重试</el-button>
      </div>
    </div>
    <el-alert title="院校库包含已核对资料与“采集待核实”记录，请查看专业备注中的状态、年份和来源。请以当年官方目录确认报考条件。" type="warning" :closable="false" />
    <div class="rows" v-loading="loading">
      <router-link v-for="school in list" :key="school.id" :to="`/schools/${school.id}`" class="school-row">
        <strong>{{ school.name }}</strong><span>{{ school.province }} · {{ school.level || '层次未登记' }}</span>
      </router-link>
      <el-empty v-if="!loading && !list.length" description="没有匹配的院校" />
    </div>
  </div>
</template>
<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { getSchoolOptions, searchSchools, type SchoolOptions } from '@/api/school'
import { useUserStore } from '@/stores/user'
import type { School } from '@/types/api'
const user = useUserStore()
const q = reactive({ province: '', level: '', majorName: '' })
const options = ref<SchoolOptions>({ provinces: [], majorNames: [] })
const optionsLoading = ref(false), optionsError = ref(false)
const list = ref<School[]>([])
const loading = ref(false)
let searchVersion = 0
async function loadOptions() {
  if (optionsLoading.value) return
  const token = user.token
  optionsLoading.value = true
  try {
    const data = await getSchoolOptions()
    if (token !== user.token) return
    options.value = data
    optionsError.value = false
  } catch {
    if (token === user.token) optionsError.value = true
  } finally { optionsLoading.value = false }
}
async function load() {
  const version = ++searchVersion
  loading.value = true
  try { const data = await searchSchools(q); if (version === searchVersion) list.value = data } finally { if (version === searchVersion) loading.value = false }
}
onMounted(() => { void loadOptions(); void load() })
</script>
<style scoped>
.schools-page { max-width: 1000px; }
.hero { background: linear-gradient(135deg,#3b6cff,#6d5cff); border-radius: 16px; padding: 28px; color: white; margin-bottom: 18px; }
.hero h1 { margin: 0; }
.search-bar { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 12px; }
.search-bar .el-input, .search-bar .el-select { width: 100%; }
.options-error { display: flex; align-items: center; gap: 12px; margin-top: 12px; }
.rows { margin: 20px 0; }
.school-row { display: flex; justify-content: space-between; padding: 18px; margin: 10px 0; background: var(--c-surface); border: 1px solid var(--c-line); border-radius: 12px; color: var(--c-ink); text-decoration: none; }
@media(max-width:600px) { .search-bar { grid-template-columns: 1fr; } .school-row { flex-direction: column; gap: 8px; } }
</style>
