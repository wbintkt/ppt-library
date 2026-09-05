<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { clearToken } from './api'
import ToastHost from './ToastHost.vue'
const router = useRouter()
const route = useRoute()
const isSearch = computed(() => route.name === 'search')
function focusMain() { document.getElementById('main-content')?.focus() }
function logout() {
  clearToken()
  router.push('/login')
}
</script>
<template>
  <div class="layout" :class="{ 'search-layout': isSearch, 'login-layout': route.name === 'login' }">
    <a href="#main-content" class="skip-link" @click.prevent="focusMain">跳到主要内容</a>
    <ToastHost />
    <header class="topbar">
      <router-link class="brand" to="/" aria-label="PPT 素材库首页">
        <span class="brand-mark" aria-hidden="true"></span><span class="brand-name">PPT 素材库</span>
      </router-link>
      <div id="header-search"></div>
      <nav v-if="route.name !== 'login'" class="nav" aria-label="主导航">
        <router-link v-if="!isSearch" to="/" class="nav-link">搜索</router-link>
        <router-link to="/library" class="nav-link">素材管理</router-link>
        <router-link to="/settings" class="nav-link">设置</router-link>
        <button class="logout-btn" @click="logout">退出</button>
      </nav>
    </header>
    <main id="main-content" class="content" tabindex="-1"><router-view /></main>
    <footer class="footer">PPT 素材库 <span aria-hidden="true">·</span> 内容有迹可循</footer>
  </div>
</template>
