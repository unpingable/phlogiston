export interface WorkspaceState { primary: string; secondary: string|null; mode: 'pinned'|'paired'; pairs: Record<string,string|null>; context: string|null }
export type WorkspaceEvent = {type:'primary'|'inspect';source:string}|{type:'secondary';source:string|null}|{type:'mode';mode:'pinned'|'paired'}|{type:'dismiss'};
export function initialState():WorkspaceState;
export function transition(state:WorkspaceState,event:WorkspaceEvent):WorkspaceState;
export function markAttentionStale(surface: Element): void;
