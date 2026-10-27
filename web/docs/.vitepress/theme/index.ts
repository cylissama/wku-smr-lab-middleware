import DefaultTheme from 'vitepress/theme'
import type { Theme } from 'vitepress'
import ArchitectureView from './ArchitectureView.vue'

export default {
  extends: DefaultTheme,
  enhanceApp({ app }) {
    // <ArchitectureView view="…" /> in any page embeds a view of web/architecture/
    app.component('ArchitectureView', ArchitectureView)
  },
} satisfies Theme
