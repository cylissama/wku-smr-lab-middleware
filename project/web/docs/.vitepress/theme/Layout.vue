<script setup lang="ts">
import DefaultTheme from 'vitepress/theme'

const { Layout } = DefaultTheme
</script>

<template>
  <Layout>
    <template #nav-bar-content-before>
      <a href="/" target="_self" class="dashboard-link">Dashboard</a>
    </template>
  </Layout>
</template>

<style scoped>
.dashboard-link {
  display: inline-flex;
  align-items: center;
  margin-right: 8px;
  padding: 0 12px;
  height: 28px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  color: #fff;
  background-color: #0891b2;
  transition: background-color 0.25s;
  white-space: nowrap;
}

.dashboard-link:hover {
  background-color: #06b6d4;
}
</style>
