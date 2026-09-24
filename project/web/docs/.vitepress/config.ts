import { defineConfig } from 'vitepress'

// https://vitepress.dev/reference/site-config
export default defineConfig({
  base: '/docs/',
  title: "SMR Documentation",
  description: "Documentation for the WKU Smart Manufacturing Research data broker middleware",
  themeConfig: {
    // https://vitepress.dev/reference/default-theme-config
    nav: [
      { text: 'Home', link: '/' },
      { text: 'Overview', link: '/overview/what-is-this' },
      { text: 'Hardware', link: '/hardware/' },
      { text: 'Data', link: '/data/database-uses' },
      { text: 'Docker', link: '/docker/compose' },
      { text: 'Network', link: '/network/topology' },
      { text: 'Expanding', link: '/expanding/' },
      { text: 'Operations', link: '/operations/running-a-test' },
    ],

    sidebar: [
      {
        text: 'Overview',
        items: [
          { text: 'What is this project?', link: '/overview/what-is-this' },
          { text: 'How is this structured?', link: '/overview/structure' },
          { text: 'Github Repos', link: '/overview/repositories' },
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
          { text: 'Accessing the database', link: '/data/accessing-database' },
          { text: 'Updating the schema', link: '/data/schema-changes' },
        ],
      },
      {
        text: 'Docker',
        items: [
          { text: 'Compose', link: '/docker/compose' },
          { text: 'Swarm', link: '/docker/swarm' },
          { text: 'Automations', link: '/docker/automations' },
          { text: 'TCP Server', link: '/docker/tcp-server' },
          { text: 'Portainer', link: '/docker/portainer' },
        ],
      },
      {
        text: 'Network',
        items: [
          { text: 'Topology', link: '/network/topology' },
          { text: 'IP Address Table', link: '/network/ip-addresses' },
          { text: 'Compose vs. Swarm parity', link: '/network/compose-vs-swarm-parity' },
        ],
      },
      {
        text: 'Expanding',
        items: [
          { text: 'Expanding the system', link: '/expanding/' },
          { text: 'Bringing a node online', link: '/expanding/swarm-nodes' },
        ],
      },
      {
        text: 'Operations',
        items: [
          { text: 'Running a test session', link: '/operations/running-a-test' },
          { text: 'Camera live feed', link: '/operations/camera-ops' },
        ],
      },
    ],

    socialLinks: [
      { icon: 'github', link: 'https://github.com/cylissama/wku-smr-lab-middleware' },
      {
        icon: {
          svg: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect><line x1="8" y1="21" x2="16" y2="21"></line><line x1="12" y1="17" x2="12" y2="21"></line></svg>',
        },
        link: '/data/dashboard',
        ariaLabel: 'Data Dashboard',
      },
    ],
  },
})
