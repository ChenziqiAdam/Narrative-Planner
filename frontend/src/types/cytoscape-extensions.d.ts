/**
 * Cytoscape 扩展模块类型声明
 */

declare module 'cytoscape-dagre' {
  import cytoscape from 'cytoscape'
  const dagre: cytoscape.Ext
  export default dagre
}

declare module 'cytoscape-cose-bilkent' {
  import cytoscape from 'cytoscape'
  const coseBilkent: cytoscape.Ext
  export default coseBilkent
}
