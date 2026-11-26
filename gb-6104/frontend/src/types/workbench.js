/**
 * @typedef {{id:number, code:string, title:string, description:string, payload:Object, created_by:string}} Case
 * @typedef {{id:number, case_id:number, case_title:string, status:string, parameter:number, result:Object|null, kind:string, parent_run_id:number|null, adjustments:Object|null, correction_code:string|null, superseded_by_code:string|null, superseded_by_run_id:number|null}} Run
 * @typedef {{run_id:number, actor:string, note:string, created_at:number}} Review
 * @typedef {{id:number, code:string, parent_run_id:number, run_id:number, adjustments:Object, note:string, digest:string, actor:string, created_at:number, replayed:boolean}} Correction
 */

/** Reject a malformed configuration before rendering its navigation. */
export function validateConfig(config) {
  if (!config || !Array.isArray(config.modules) || config.modules.length !== 4 ||
      !Number.isInteger(config.default_parameter) || !config.title) {
    throw new Error("工作台配置不完整");
  }
  return config;
}
