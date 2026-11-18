// The published address, for later: GitHub Pages serves the site under the repository name.
export const site = 'https://acceluma.github.io';
export const base = '/optodraw';
export const groups = ['Start', 'Drawing', 'Outputs', 'Guides', 'Reference', 'Project'];
// The old MkDocs addresses keep working: each one sends the reader to the page that holds its content now.
export const redirects = {
  '/installation/': '/get-started/',
  '/quickstart/': '/get-started/',
  '/flagship_demo/': '/examples/',
  '/editor/': '/guides/editor/',
  '/free_space_optics/': '/free-space/',
  '/ray_tracing/': '/ray-tracing/',
  '/onchip_layout/': '/chips/',
  '/migration_3.0/': '/chips/',
  '/schematic_rendering/': '/figures/',
  '/publication/': '/figures/',
  '/xsection_process/': '/gds/',
  '/xsection_validation/': '/gds/',
  '/studio_rendering/': '/3d/',
  '/interactive_scenes/': '/3d/',
  '/video/': '/animation/',
  '/teaching_animations/': '/animation/',
  '/api/': '/reference/api/',
  '/new_part/': '/guides/your-own-parts/',
  '/compatibility/': '/reference/compatibility/',
  '/optiland/': '/reference/compatibility/',
  '/architecture/': '/project/',
  '/ecosystem/': '/project/',
  '/citing/': '/project/'
};
