<script setup lang="ts">
import DefaultTheme from 'vitepress/theme'
import { useData } from 'vitepress'

const { Layout } = DefaultTheme
const { theme } = useData()
</script>

<template>
  <Layout>
    <template #nav-bar-content-before>
      <a href="/" target="_self" class="smr-nav-btn">Data Dashboard</a>
      <a href="/docs/" class="smr-nav-btn smr-nav-btn--active">Documentation</a>

      <a
        v-if="theme.aiUrl"
        :href="theme.aiUrl"
        target="_blank"
        rel="noreferrer"
        class="smr-nav-btn smr-nav-btn--icon"
      >AI</a>

      <a
        v-if="theme.twinsUrl"
        :href="theme.twinsUrl"
        target="_blank"
        rel="noreferrer"
        class="smr-nav-btn smr-nav-btn--icon"
      >Twins</a>
    </template>
  </Layout>
</template>

<style scoped>
.smr-nav-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-right: 8px;
  padding: 0 12px;
  height: 32px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  color: #fff;
  background-color: #0891b2;
  transition: background-color 0.25s;
  white-space: nowrap;
}

.smr-nav-btn:hover {
  background-color: #06b6d4;
}

.smr-nav-btn--active {
  color: #0f172a;
  background-color: #fff;
}

.smr-nav-btn--active:hover {
  background-color: #fff;
}

.smr-nav-btn--icon {
  padding: 0 10px;
}
</style>
