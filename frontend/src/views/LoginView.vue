<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, setToken } from '../api'
import { toast } from '../toast'

const router = useRouter()
const username = ref('admin')
const password = ref('')
const loading = ref(false)

async function doLogin() {
  if (!username.value || !password.value) {
    toast('请输入用户名和密码', 'error')
    return
  }
  loading.value = true
  try {
    const resp = await api.login(username.value, password.value)
    setToken(resp.access_token)
    toast('登录成功')
    router.push('/')
  } catch (e: any) {
    toast(e.message || '登录失败', 'error')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <div class="login-card fade-up">
      <div class="login-mark">◆</div>
      <h1 class="login-title">PPT 素材智能检索系统</h1>
      <p class="login-sub">以「页」为单位的跨模态素材管理与检索</p>
      <form class="login-form" @submit.prevent="doLogin">
        <input v-model="username" class="text-input" placeholder="用户名" autocomplete="username" />
        <input v-model="password" type="password" class="text-input" placeholder="密码" autocomplete="current-password" />
        <button class="btn primary login-btn" :disabled="loading" type="submit">
          {{ loading ? '登录中...' : '登 录' }}
        </button>
      </form>
      <p class="login-foot">内部系统 · 仅限授权用户使用</p>
    </div>
  </div>
</template>

<style scoped>
.login-wrap {
  min-height: calc(100vh - 60px);
  display: flex; align-items: center; justify-content: center;
  background:
    radial-gradient(ellipse at 50% 20%, rgba(230, 0, 18, 0.08), transparent 60%),
    var(--bg);
}
.login-card {
  width: 380px; padding: 52px 44px; text-align: center;
  background: var(--white); border: 1px solid var(--brand-line); border-radius: 16px;
  box-shadow: var(--shadow);
}
.login-mark { color: var(--brand); font-size: 26px; margin-bottom: 16px; }
.login-title { font-size: 21px; letter-spacing: 3px; margin-bottom: 8px; }
.login-sub { color: var(--ink-faint); font-size: 12.5px; margin-bottom: 34px; letter-spacing: 1px; }
.login-form { display: flex; flex-direction: column; gap: 14px; }
.login-btn { justify-content: center; margin-top: 8px; }
.login-foot { margin-top: 30px; font-size: 11.5px; color: var(--ink-faint); letter-spacing: 1px; }
</style>
