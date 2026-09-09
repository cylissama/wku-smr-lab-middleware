import { defineConfig } from 'vitepress'

// https://vitepress.dev/reference/site-config
export default defineConfig({
  base: '/docs/',
  title: "SMR Documentation",
  description: "Documentation for the WKU Smart Manufacturing Research data broker middleware",
  themeConfig: {
    // Site title in the shared nav bar matches the main app's header exactly.
    siteTitle: 'Smart Manufacturing Research',

    // Section links (Overview/Hardware/etc.) live in the sidebar below, not
    // the top nav, to keep the header identical to the Data Dashboard's.
    nav: [],

    // Passed through to the shared nav bar (see theme/Layout.vue) so the
    // AI/Twins buttons match the main app's - both read from the same
    // VITE_AI_URL / VITE_TWINS_URL build args.
    aiUrl: process.env.VITE_AI_URL || '',
    twinsUrl: process.env.VITE_TWINS_URL || '',

    sidebar: [
      {
        text: 'Overview',
        items: [
          { text: 'What is this project?', link: '/overview/what-is-this' },
          { text: 'How is this structured?', link: '/overview/structure' },
        ],
      },
      {
        text: 'Hardware',
        items: [
          { text: 'The hardware behind the project', link: '/hardware/' },
          { text: 'Data Broker Mini PC', link: '/hardware/data-broker-mini-pc' },
          { text: 'IMU Nodes', link: '/hardware/imu' },
          { text: 'Camera Nodes', link: '/hardware/camera' },
          { text: 'Robot Arm', link: '/hardware/robot-arm' },
        ],
      },
      {
        text: 'Data',
        items: [
          { text: 'Database uses', link: '/data/database-uses' },
          { text: 'Database structure', link: '/data/database-structure' },
        ],
      },
      {
        text: 'Docker',
        items: [
          { text: 'Compose', link: '/docker/compose' },
          { text: 'Swarm', link: '/docker/swarm' },
          { text: 'Automations', link: '/docker/automations' },
          { text: 'TCP Server', link: '/docker/tcp-server' },
        ],
      },
      {
        text: 'Network',
        items: [
          { text: 'Topology', link: '/network/topology' },
        ],
      },
      {
        text: 'Expanding',
        items: [
          { text: 'Expanding the system', link: '/expanding/' },
          { text: 'Bringing a node online', link: '/expanding/swarm-nodes' },
        ],
      },
    ],

    socialLinks: [
      { icon: 'github', link: 'https://github.com/cylissama/wku-smr-lab-middleware' },
    ],
  },
})
