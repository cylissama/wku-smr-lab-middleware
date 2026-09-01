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
    ],

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
      { icon: 'github', link: 'https://github.com/Mseavers1/CS560-Smart-Manufacturing-Data' },
    ],
  },
})
