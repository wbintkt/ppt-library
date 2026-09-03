<script setup lang="ts">
import { useRouter } from 'vue-router'
import { clearToken } from './api'
import ToastHost from './ToastHost.vue'

const router = useRouter()
const nav = [
  { name: 'search', label: '语义检索', icon: '◇' },
  { name: 'library', label: '素材库', icon: '◆' },
  { name: 'settings', label: '系统设置', icon: '◇' },
]

function logout() {
  clearToken()
  router.push('/login')
}
</script>

<template>
  <div class="layout">
    <ToastHost />
    <header class="topbar">
      <div class="brand" @click="router.push('/')">
        <span class="brand-mark">◆</span>
        <span class="brand-name">PPT 素材库</span>
        <span class="brand-sub">智能检索系统</span>
      </div>
      <nav class="nav">
        <router-link v-for="n in nav" :key="n.name" :to="{ name: n.name }" class="nav-link">
          <span class="nav-icon">{{ n.icon }}</span>{{ n.label }}
        </router-link>
      </nav>
      <button class="logout-btn" @click="logout">退出</button>
    </header>
    <main class="content">
      <router-view />
    </main>
    <footer class="footer">◆ 以「页」为单位的跨模态 PPT 素材检索</footer>
  </div>
</template>
