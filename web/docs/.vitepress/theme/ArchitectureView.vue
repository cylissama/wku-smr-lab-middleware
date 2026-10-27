<script setup lang="ts">
// Embeds one view of the architecture model (web/architecture/) with the
// <likec4-view> web component that the architecture build publishes at
// /architecture/likec4-views.js. Under `npm run docs:dev` that file isn't
// served, so only the link below shows.
import { onMounted, ref } from 'vue'
import { useData } from 'vitepress'

// variant: show a dynamic view as 'diagram' or 'sequence' instead of its default
const props = defineProps<{ view: string; title?: string; variant?: 'diagram' | 'sequence' }>()
const { isDark } = useData()
const loaded = ref(false)

const SCRIPT = '/architecture/likec4-views.js'

function loadScript(): Promise<void> {
  if (customElements.get('likec4-view')) return Promise.resolve()
  let script = document.querySelector<HTMLScriptElement>(`script[src="${SCRIPT}"]`)
  if (!script) {
    script = document.createElement('script')
    script.src = SCRIPT
    document.head.appendChild(script)
  }
  return customElements.whenDefined('likec4-view').then(() => undefined)
}

onMounted(() => {
  loadScript().then(() => { loaded.value = true })
})
</script>

<template>
  <figure class="architecture-view">
    <likec4-view
      v-if="loaded"
      :view-id="props.view"
      :dynamic-variant="props.variant"
      :color-scheme="isDark ? 'dark' : 'light'"
    />
    <figcaption>
      <a :href="`/architecture/view/${props.view}/`" target="_self">
        {{ props.title ?? 'Open this diagram' }} in the interactive architecture site ↗
      </a>
    </figcaption>
  </figure>
</template>

<style scoped>
.architecture-view {
  margin: 16px 0;
}
.architecture-view likec4-view {
  display: block;
  border: 1px solid var(--vp-c-divider);
  border-radius: 8px;
  overflow: hidden;
}
.architecture-view figcaption {
  margin-top: 6px;
  font-size: 14px;
}
</style>
