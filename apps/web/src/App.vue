<script setup lang="ts">
import { computed, onMounted, onUnmounted, provide, ref, watch } from 'vue'
import { acceptPrivacy, analyze, analyzePlan, appendGameMove, beginOidcLogin, cancelDeletion, coachChat, createGame, deleteGame, engineMove, forgotPassword, getAuthMethods, getGames, getHealth, getMe, getOpenings, getPrivacyConfig, importGame, loginEmail, logout, persistReview, recognizeSetupImage, registerEmail, requestEmailVerification, resetEngine, resetPassword, review, updateGameEvents, verifyEmail, type Analysis, type AuthMethods, type AuthUser, type CoachMessage, type Health, type OpeningLine, type PersistedEngineSettings, type PersistedGame, type PersistedGameEvent, type PlanAnalysis, type PrivacyConfig, type ReviewItem, type ReviewResponse } from './lib/api'
import { migrateLegacyGames } from './lib/legacyGameMigration'
import { applyMove, clonePosition, describeUci, fromUci, legalTargets, movePiece, parseFen, perpetualCheckSide, perpetualChaseSide, setPiece, START_FEN, toFen, toUci, validateSetupPosition, type Piece, type Position } from './lib/xiangqi'
import { listRecognizedPieces } from './lib/recognitionPositions'
import { recognitionControls } from './lib/recognitionState'
import BoardView from './components/BoardView.vue'
import AnalysisView from './components/AnalysisView.vue'
import ReviewView from './components/ReviewView.vue'
import CoachView from './components/CoachView.vue'
import GamesView, { type SavedGameView } from './components/GamesView.vue'
import EngineSettings from './components/EngineSettings.vue'
import SetupControls from './components/SetupControls.vue'
import { createRequestSequence } from './lib/requestSequence'
import { collectHintCandidates } from './lib/hintCandidates'
import { normalizeSavedEngineSettings, opponentPresets } from './lib/engineStrength'
import { parseBoardTheme, type BoardTheme } from './lib/boardTheme'
import { coachPosition } from './lib/coachPosition'
import { nextStepSession } from './lib/coachNextStep'
import { advanceMoves, undoMoves } from './lib/moveTimeline'
import { createHintEvent, createUndoEvent, type GameEvent } from './lib/gameEvents'
import { waitForMinimumElapsed } from './lib/minimumDelay'
import { playMoveSteps } from './lib/movePlayback'
import ReviewDialog from './components/ReviewDialog.vue'
import { useReviewSession, reviewSnapshotKey, type ReviewSnapshot } from './lib/useReviewSession'
import { reviewDisabledReason } from './lib/reviewSummary'
import { terminalStatus } from './lib/xiangqi'

type Tab = 'duel'|'analysis'|'review'|'coach'|'games'
const tabs: { id: Tab; label: string }[] = [{ id:'duel',label:'对弈' },{ id:'analysis',label:'分析' },{ id:'review',label:'复盘' },{ id:'coach',label:'教练' },{ id:'games',label:'棋局' }]
const tab = ref<Tab>('duel')
const boardTheme = ref<BoardTheme>('classic')
const health = ref<Health|null>(null)
const healthError = ref('')
const lastHealthCheck = ref<Date|null>(null)
const llmLastError = ref('')
const position = ref<Position>(parseFen(START_FEN))
const selected = ref<[number,number]|null>(null)
const history = ref<string[]>([])
const futureMoves = ref<string[]>([])
const redoBatchSize = ref<number|null>(null)
const baseFen = ref(START_FEN)
const analysis = ref<Analysis|null>(null)
const status = ref<'idle'|'thinking'|'error'>('idle')
const replayBusy = ref(false)
const message = ref('准备开始')
const side = ref<'red'|'black'|'watch'>('red')
const depth = ref(4), movetime = ref(700), threads = ref(1), hashMb = ref(64)
const analysisMultiPv = ref(3)
const hintDepth = ref(10), hintMovetime = ref(1500), hintMultiPv = ref(3), showHintCandidates = ref(true)
const allowSuboptimal = ref(true)
const difficulty = ref<'companion'|'beginner'|'progress'|'serious'|'full'|'custom'>('progress')
const hintDifficulty = ref<'beginner'|'regular'|'elite'|'custom'>('regular')
type HintDifficulty = 'beginner'|'regular'|'elite'|'custom'
const hintUsed = ref(0)
const fenInput = ref(START_FEN)
const planIdea = ref(''), planMove = ref('')
const planAnalysis = ref<PlanAnalysis|null>(null)
const planBusy = ref(false)
const hint = ref<{move:string|null;label:string|null}>({move:null,label:null})
const hintCandidates = ref<Analysis['lines']>([])
const reviewResult = ref<ReviewResponse|null>(null)
const reviewBusy = ref(false), reviewError = ref(''), selectedPly = ref<number|null>(null)
const openings = ref<OpeningLine[]>([])
const selectedLine = ref<number|null>(null)
const selectedMove = ref<string|null>(null)
const coachMessages = ref<CoachMessage[]>([])
const coachBusy = ref(false), coachUnavailable = ref(''), coachContext = ref('')
const studyMode = ref(false)
const setupMode = ref(false)
const setupDraft = ref<Position|null>(null)
type SetupTool = 'move' | 'clear' | Piece
const setupTool = ref<SetupTool>('move')
const setupSelectedSquare = ref<[number, number] | null>(null)
const setupHistory = ref<Position[]>([])
const setupErrors = ref<string[]>([])
const recognitionPosition = ref<Position|null>(null)
const recognitionBusy = ref(false)
const recognitionAbortController = ref<AbortController|null>(null)
const recognitionRequests = createRequestSequence()
const recognitionError = ref('')
const recognitionPreviewUrl = ref('')
const recognitionPieceCount = ref<number|null>(null)
const recognitionWarnings = ref<string[]>([])
const recognitionApplied = ref(false)
const recognitionUi = computed(()=>recognitionControls(recognitionPosition.value!==null, recognitionApplied.value))
const canApplyRecognition = computed(()=>recognitionUi.value.canApply&&recognitionPosition.value!==null&&validateSetupPosition(recognitionPosition.value).length===0)
const recognitionPieces = computed(()=>recognitionPosition.value?listRecognizedPieces(recognitionPosition.value):[])
const saveNameDialogOpen = ref(false)
const saveGameName = ref('')
const saveNameError = ref('')
const currentUser = ref<AuthUser|null>(null)
const privacyConfig = ref<PrivacyConfig>({policy_version:'v1.0',effective_date:'',operator_name:'',contact_email:'',ready_for_publication:false})
const privacyAccepted = ref(false)
const privacyBusy = ref(false)
const authMethods = ref<AuthMethods>({ email: true, oidc: false, email_verification_required: false })
const emailAuthOpen = ref(false)
const emailAuthTab = ref<'login'|'register'|'forgot'|'reset'>('login')
const emailAuthEmail = ref('')
const emailAuthPassword = ref('')
const emailAuthDisplayName = ref('')
const emailAuthBusy = ref(false)
const emailAuthError = ref('')
const emailAuthNotice = ref('')
const emailActionToken = ref('')
let healthRefreshTimer: number | undefined
provide('xiangqi-setup-mode', setupMode)

const presets = {...opponentPresets,custom:{label:'自定义',description:'使用自定义搜索参数',depth:8,movetime:1500,threads:1,hashMb:256}} as const
const ENGINE_MOVE_MINIMUM_DELAY_MS = 1500
const hintPresets = {
  beginner:{depth:5,movetime:300,multipv:1},
  regular:{depth:10,movetime:1500,multipv:3},
  elite:{depth:15,movetime:5000,multipv:5},
  custom:{depth:15,movetime:0,multipv:3},
} as const
type Difficulty = keyof typeof presets
const GAME_STORAGE_KEY = 'pikafish-lab-games-v1'
const SETTINGS_STORAGE_KEY = 'pikafish-lab-settings-v1'
const BOARD_THEME_STORAGE_KEY = 'pikafish-lab-board-theme-v1'
interface SavedGame extends SavedGameView {
  baseFen:string; depth:number; movetime:number; multipv:number; difficulty:Difficulty
  difficultySettings:PersistedEngineSettings & {hintLimit:number|null}
  hintSettings?:{difficulty?:HintDifficulty;depth:number;movetime_ms:number;multipv:number;showCandidates?:boolean}; hintsUsed:number; reviewCache?:{snapshotKey:string;result:ReviewResponse;generatedAt:string}; serverVersion?:number; syncedMoves?:number; syncedEvents?:number
}
const savedGames = ref<SavedGame[]>([])
const gameEvents = ref<GameEvent[]>([])
const currentGameId = ref<string|null>(null)
const maxThreads = computed(()=>Math.max(1,globalThis.navigator?.hardwareConcurrency||1))
const engineReady = computed(()=>health.value?.engine_ready===true)
const reviewDialogOpen = ref(false)
const currentReviewSnapshot = computed<ReviewSnapshot>(()=>({fen:baseFen.value,moves:[...history.value],events:[...gameEvents.value],side:side.value,gameId:currentGameId.value}))
const quickReview = useReviewSession(async snapshot=>{
  const payload={fen:snapshot.fen,moves:[...snapshot.moves],depth:8,movetime_ms:350,threads:1,hash_mb:128}
  const saved=savedGames.value.find(game=>game.id===snapshot.gameId&&game.serverVersion!==undefined&&game.syncedMoves===snapshot.moves.length&&game.baseFen===snapshot.fen&&JSON.stringify(game.moves)===JSON.stringify(snapshot.moves))
  if(saved){try{return await persistReview(saved.id,payload)}catch(error){if(!(error instanceof Error&&'status' in error&&error.status===409))throw error}}
  return review(payload)
})
const quickReviewReason = computed(()=>reviewDisabledReason({setup:setupMode.value,thinking:status.value==='thinking',engineReady:engineReady.value,plies:history.value.length}))
const quickReviewStale = computed(()=>quickReview.isStale(currentReviewSnapshot.value))
const gameTerminal = computed(()=>setupMode.value?null:terminalStatus(position.value))
let lastAutomaticReview = ''
function cachedReviewFor(snapshot:ReviewSnapshot){
  const game=savedGames.value.find(item=>item.id===snapshot.gameId)
  const cache=game?.reviewCache
  return cache?.snapshotKey===reviewSnapshotKey(snapshot)?cache:undefined
}
function saveQuickReview(snapshot:ReviewSnapshot,result:ReviewResponse){
  const game=savedGames.value.find(item=>item.id===snapshot.gameId)
  if(!game)return
  game.reviewCache={snapshotKey:reviewSnapshotKey(snapshot),result,generatedAt:new Date().toISOString()}
  persistGames()
}
async function startQuickReview(force=false){
  if(quickReviewReason.value)return
  const snapshot=currentReviewSnapshot.value
  if(!force){
    const cached=cachedReviewFor(snapshot)
    if(cached){quickReview.restore(snapshot,cached.result);return}
    if(!quickReviewStale.value&&(quickReview.result.value||quickReview.busy.value))return
  }
  const result=await quickReview.start(snapshot)
  if(result&&reviewSnapshotKey(snapshot)===reviewSnapshotKey(currentReviewSnapshot.value))saveQuickReview(snapshot,result)
}
function openReview(retry=false){
  if(quickReviewReason.value)return
  reviewDialogOpen.value=true
  if(retry||quickReviewStale.value||!quickReview.snapshot.value)void startQuickReview(retry)
}
const engineLabel = computed(()=>!health.value?'检测中':health.value.engine_ready?'已连接':'未配置')
const serviceItems = computed(()=>[
  { key:'web', label:'前端', state:'ok', text:'在线' },
  { key:'api', label:'API 后端', state:healthError.value?'error':'ok', text:healthError.value?'无法连接':'在线' },
  { key:'engine', label:'Pikafish', state:health.value?.engine_ready?'ok':'warn', text:!health.value?'检测中':health.value.engine_ready?'已连接':health.value.engine_configured?'启动失败':'未配置' },
  { key:'llm', label:'大模型', state:llmLastError.value?'error':health.value?.llm_configured?'ok':'warn', text:llmLastError.value?'最近请求失败':!health.value?'检测中':health.value.llm_configured?health.value.llm_model??'已配置':'未配置' },
])
const healthCheckedLabel = computed(()=>lastHealthCheck.value?`上次检查 ${lastHealthCheck.value.toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit',second:'2-digit'})}`:'尚未检查')
const turnLabel = computed(()=>position.value.redToMove?'红方':'黑方')
const legal = computed(()=>selected.value?legalTargets(position.value,selected.value):[])
const validSettings = computed(()=>depth.value>=1&&depth.value<=64&&movetime.value>=0&&movetime.value<=120000&&threads.value>=1&&threads.value<=maxThreads.value&&hashMb.value>=16&&hashMb.value<=8192)
const undoSteps = computed(()=>{
  if(!history.value.length)return 0
  if(!engineReady.value||side.value==='watch')return Math.min(2,history.value.length)
  if(position.value.redToMove!==(side.value==='red'))return 1
  return history.value.length>=2?2:0
})
const canUndo = computed(()=>!setupMode.value&&undoSteps.value>0&&status.value!=='thinking'&&!replayBusy.value)
const redoSteps = computed(()=>futureMoves.value.length?Math.min(redoBatchSize.value ?? futureMoves.value.length, futureMoves.value.length):0)
const canRedo = computed(()=>!setupMode.value&&redoSteps.value>0&&status.value!=='thinking'&&!studyMode.value&&!replayBusy.value)
const canHumanMove = computed(()=>setupMode.value?recognitionUi.value.canEdit:(!replayBusy.value&&!gameTerminal.value&&!studyMode.value&&side.value!=='watch'&&(!engineReady.value||side.value===(position.value.redToMove?'red':'black'))))
const canRequestHint = computed(()=>engineReady.value&&!replayBusy.value&&!setupMode.value&&!studyMode.value&&side.value!=='watch'&&status.value!=='thinking')
const displayPosition = computed(()=>{
  if(setupMode.value&&setupDraft.value)return setupDraft.value
  if(selectedPly.value===null||!reviewResult.value)return position.value
  try{return rebuildPosition(baseFen.value,history.value.slice(0,selectedPly.value-1))}catch{return position.value}
})
const displayedLastMove = computed(()=>setupMode.value?null:selectedPly.value!==null?reviewResult.value?.items[selectedPly.value-1]?.move??null:history.value.at(-1)??null)
const highlightMove = computed(()=>setupMode.value?null:selectedPly.value!==null?displayedLastMove.value:studyMode.value?selectedMove.value:hint.value.move)
const liveFen = computed(()=>studyMode.value?toFen(displayPosition.value):toFen(position.value))
const liveMoves = computed(()=>selectedPly.value!==null?history.value.slice(0,selectedPly.value-1):history.value)

function clearStudy(){studyMode.value=false;selectedPly.value=null;selectedLine.value=null;selectedMove.value=null}
function clearRecognition(){recognitionRequests.invalidate();recognitionAbortController.value?.abort();recognitionAbortController.value=null;recognitionBusy.value=false;recognitionPosition.value=null;recognitionApplied.value=false;recognitionPieceCount.value=null;recognitionWarnings.value=[];recognitionError.value='';if(recognitionPreviewUrl.value)URL.revokeObjectURL(recognitionPreviewUrl.value);recognitionPreviewUrl.value=''}
function cancelRecognition(){recognitionRequests.invalidate();recognitionAbortController.value?.abort();recognitionAbortController.value=null;recognitionBusy.value=false;recognitionError.value='已取消图片识别';message.value='已取消图片识别'}
function startSetup(){if(status.value==='thinking')return;setupMode.value=true;setupDraft.value=clonePosition(position.value);setupTool.value='move';setupSelectedSquare.value=null;setupHistory.value=[];setupErrors.value=[];clearRecognition();clearStudy();message.value='摆棋模式：移动、添加、删除棋子，或从图片识别局面'}
function cancelSetup(){clearRecognition();setupMode.value=false;setupDraft.value=null;setupTool.value='move';setupSelectedSquare.value=null;setupHistory.value=[];setupErrors.value=[];message.value='已取消摆棋，已恢复进入摆棋前的局面'}
async function recognizeSetup(file:File){
  if(!setupMode.value)return
  clearRecognition();const requestId=recognitionRequests.next();const controller=new AbortController();recognitionPreviewUrl.value=URL.createObjectURL(file);recognitionBusy.value=true;recognitionAbortController.value=controller
  const allowed=['image/png','image/jpeg','image/webp']
  if(!allowed.includes(file.type)){recognitionError.value='只支持 PNG、JPEG 或 WebP 棋盘图片';recognitionBusy.value=false;recognitionAbortController.value=null;return}
  if(file.size>8*1024*1024){recognitionError.value='图片不能超过 8MB';recognitionBusy.value=false;recognitionAbortController.value=null;return}
  try{
    const result=await recognizeSetupImage(file,controller.signal)
    if(!recognitionRequests.isCurrent(requestId))return
    const recognized=parseFen(result.fen)
    recognitionPosition.value=recognized;recognitionPieceCount.value=result.piece_count
    recognitionWarnings.value=[...result.warnings]
    setupErrors.value=[]
    message.value='图片局面已识别，请检查棋盘后采用'
  }catch(error){if(recognitionRequests.isCurrent(requestId))recognitionError.value=error instanceof Error?error.message:'棋盘图片识别失败'}finally{if(recognitionRequests.isCurrent(requestId)){recognitionBusy.value=false;recognitionAbortController.value=null}}
}
function applyRecognizedPosition(){
  if(!recognitionPosition.value)return
  const errors=validateSetupPosition(recognitionPosition.value)
  if(errors.length){recognitionError.value=errors.join('；');return}
  recordSetupMutation(clonePosition(recognitionPosition.value));recognitionApplied.value=true;message.value='已采用图片识别局面，可继续编辑或撤销'
}
function recordSetupMutation(next:Position){if(!setupDraft.value)return;setupHistory.value.push(clonePosition(setupDraft.value));setupDraft.value=next;setupSelectedSquare.value=null;setupErrors.value=[]}
function undoSetup(){const previous=setupHistory.value.pop();if(!previous)return;setupDraft.value=previous;setupSelectedSquare.value=null;setupErrors.value=[];message.value='已撤销上一次摆棋操作'}
function clearSetupBoard(){if(!setupDraft.value)return;recordSetupMutation(parseFen('9/9/9/9/9/9/9/9/9/9 w - - 0 1'))}
function resetSetupBoard(){if(!setupDraft.value)return;recordSetupMutation(parseFen(START_FEN))}
function setSetupTurn(redToMove:boolean){if(!setupDraft.value||setupDraft.value.redToMove===redToMove)return;recordSetupMutation({...clonePosition(setupDraft.value),redToMove})}
function placeSetupPiece(row:number,col:number){
  if(!setupMode.value||!setupDraft.value)return
  const current=setupDraft.value
  if(setupTool.value==='move'){
    const piece=current.board[row][col]
    if(!setupSelectedSquare.value){if(piece!=='.')setupSelectedSquare.value=[row,col];return}
    const source=setupSelectedSquare.value
    if(source[0]===row&&source[1]===col){setupSelectedSquare.value=null;return}
    try{recordSetupMutation(movePiece(current,source,[row,col]))}catch{setupSelectedSquare.value=null}
    return
  }
  if(setupTool.value==='clear'){
    if(current.board[row][col]!=='.')recordSetupMutation(setPiece(current,row,col,'.'))
    return
  }
  if(current.board[row][col]!==setupTool.value)recordSetupMutation(setPiece(current,row,col,setupTool.value))
}
function finishSetup(){if(!setupDraft.value)return;if(recognitionUi.value.pending){recognitionError.value='请先采用或取消图片识别结果';return}const errors=validateSetupPosition(setupDraft.value);if(errors.length){setupErrors.value=errors;message.value='摆棋局面还不能开始对弈';return}const next=clonePosition(setupDraft.value);position.value={...next,redToMove:next.redToMove};baseFen.value=toFen(position.value);fenInput.value=baseFen.value;history.value=[];gameEvents.value=[];futureMoves.value=[];redoBatchSize.value=null;currentGameId.value=null;selected.value=null;analysis.value=null;hint.value={move:null,label:null};clearReview();clearStudy();clearRecognition();setupMode.value=false;setupDraft.value=null;setupTool.value='move';setupSelectedSquare.value=null;setupHistory.value=[];setupErrors.value=[];message.value='摆棋完成，可以开始对弈';if(side.value==='black'&&position.value.redToMove&&engineReady.value)void askEngine(true)}
function clearReview(){reviewResult.value=null;reviewError.value='';selectedPly.value=null}
function applyDifficulty(value:Difficulty){difficulty.value=value;const preset=presets[value];if(value!=='custom'){depth.value=preset.depth;movetime.value=preset.movetime;threads.value=Math.min(preset.threads,maxThreads.value);hashMb.value=preset.hashMb}hint.value={move:null,label:null}}
function applyHintDifficulty(value:HintDifficulty){hintDifficulty.value=value;const preset=hintPresets[value];if(value!=='custom'){hintDepth.value=preset.depth;hintMovetime.value=preset.movetime;hintMultiPv.value=preset.multipv}hint.value={move:null,label:null};hintCandidates.value=[]}
function setShowHintCandidates(value:boolean){showHintCandidates.value=value;if(!value)hintCandidates.value=[]}
function saveEngineSettings(notify=false){try{localStorage.setItem(SETTINGS_STORAGE_KEY,JSON.stringify({difficulty:difficulty.value,allowSuboptimal:allowSuboptimal.value,depth:depth.value,movetime:movetime.value,threads:threads.value,hashMb:hashMb.value,hintDifficulty:hintDifficulty.value,hintDepth:hintDepth.value,hintMovetime:hintMovetime.value,hintMultiPv:hintMultiPv.value,showHintCandidates:showHintCandidates.value}));if(notify)message.value='引擎参数已保存，刷新后仍会保留'}catch{message.value='浏览器存储不可用，参数仅保留在当前页面'}}
function readEngineSettings(){try{const value=JSON.parse(localStorage.getItem(SETTINGS_STORAGE_KEY)??'null');if(!value||typeof value!=='object')return;const settings=normalizeSavedEngineSettings(value);difficulty.value=settings.difficulty;allowSuboptimal.value=settings.allow_suboptimal;depth.value=settings.depth;movetime.value=settings.movetime_ms;threads.value=Math.min(settings.threads,maxThreads.value);hashMb.value=settings.hash_mb;if(value.hintDifficulty in hintPresets)hintDifficulty.value=value.hintDifficulty;if(Number.isFinite(value.hintDepth))hintDepth.value=value.hintDepth;if(Number.isFinite(value.hintMovetime))hintMovetime.value=value.hintMovetime;if(Number.isFinite(value.hintMultiPv))hintMultiPv.value=Math.min(5,Math.max(1,value.hintMultiPv));if(typeof value.showHintCandidates==='boolean')showHintCandidates.value=value.showHintCandidates}catch{}}
function readBoardTheme(){try{boardTheme.value=parseBoardTheme(localStorage.getItem(BOARD_THEME_STORAGE_KEY))}catch{boardTheme.value='classic'}}
function normalizeReviewCache(value:unknown):SavedGame['reviewCache']|undefined{
  if(!value||typeof value!=='object')return undefined
  const cache=value as {snapshotKey?:unknown;generatedAt?:unknown;result?:unknown}
  if(typeof cache.snapshotKey!=='string'||!cache.result||typeof cache.result!=='object'||!Array.isArray((cache.result as {items?:unknown}).items))return undefined
  return{snapshotKey:cache.snapshotKey,result:cache.result as ReviewResponse,generatedAt:typeof cache.generatedAt==='string'?cache.generatedAt:new Date(0).toISOString()}
}
function readSavedGames(){
  try{const value=JSON.parse(localStorage.getItem(GAME_STORAGE_KEY)??'[]');savedGames.value=Array.isArray(value)?value.filter((g:any)=>g&&typeof g.id==='string'&&typeof g.baseFen==='string'&&Array.isArray(g.moves)).map((g:any)=>{const settings=normalizeSavedEngineSettings(g);return{...g,events:Array.isArray(g.events)?g.events:[],reviewCache:normalizeReviewCache(g.reviewCache),difficulty:settings.difficulty,difficultySettings:{...settings,hintLimit:null},hintSettings:{...g.hintSettings,difficulty:['beginner','regular','elite','custom'].includes(g.hintSettings?.difficulty)?g.hintSettings.difficulty:'regular',depth:g.hintSettings?.depth??g.depth??10,movetime_ms:g.hintSettings?.movetime_ms??g.movetime??1500,multipv:g.hintSettings?.multipv??1},hintsUsed:g.hintsUsed??0}}):[]}catch{savedGames.value=[]}
}
function serverGameRecord(game:PersistedGame):SavedGame{
  const settings=normalizeSavedEngineSettings(game.engine_settings)
  return{id:game.id,name:game.name??'',startedAt:game.created_at,updatedAt:game.updated_at,baseFen:game.initial_fen,moves:game.moves.map(move=>move.uci),events:game.events??[],side:'watch',depth:settings.depth,movetime:settings.movetime_ms,multipv:3,difficulty:settings.difficulty,difficultySettings:{...settings,hintLimit:null},hintSettings:{difficulty:'regular',depth:10,movetime_ms:1500,multipv:3,showCandidates:true},hintsUsed:0,serverVersion:game.version,syncedMoves:game.moves.length,syncedEvents:game.events?.length??0}
}
function gameEngineSettings(game:SavedGame):PersistedEngineSettings{return{difficulty:game.difficulty,allow_suboptimal:game.difficultySettings.allow_suboptimal,depth:game.difficultySettings.depth,movetime_ms:game.difficultySettings.movetime_ms,threads:game.difficultySettings.threads,hash_mb:game.difficultySettings.hash_mb}}
interface GameMigrationResult { migrated:number; failed:number }
async function migrateLocalGames():Promise<GameMigrationResult>{
  const imported=await migrateLegacyGames(savedGames.value,async(game)=>{
    const localId=game.id
    const remote=await importGame({legacy_id:localId,name:game.name||undefined,initial_fen:game.baseFen,moves:game.moves,engine_settings:gameEngineSettings(game),events:game.events})
    game.id=remote.id;game.serverVersion=remote.version;game.syncedMoves=remote.moves.length;game.syncedEvents=remote.events.length
    if(currentGameId.value===localId)currentGameId.value=remote.id
    persistGames()
    return remote
  })
  let migrated=imported.imported.length,failed=imported.failed.length
  const partialGames=savedGames.value.filter(game=>game.serverVersion!==undefined&&((game.syncedMoves??0)<game.moves.length||(game.syncedEvents??0)<game.events.length))
  for(const game of partialGames){
    try{await syncCurrentGame(game);migrated++}catch{failed++}
  }
  return{migrated,failed}
}
async function loadServerGames():Promise<GameMigrationResult>{
  const empty={migrated:0,failed:0}
  try{currentUser.value=await getMe()}catch{currentUser.value=null;return empty}
  if(currentUser.value.status!=='active'||currentUser.value.privacy_accepted===false)return empty
  try{
    const remote=await getGames(),localGames=savedGames.value,remoteGames=remote.map(serverGameRecord),remoteIds=new Set(remoteGames.map(game=>game.id))
    const merged=remoteGames.map(remoteGame=>{
      const local=localGames.find(game=>game.id===remoteGame.id)
      if(!local)return remoteGame
      const events=[...remoteGame.events,...local.events.filter(event=>!remoteGame.events.some(saved=>saved.id===event.id))]
      return{...remoteGame,...local,events,serverVersion:remoteGame.serverVersion,syncedMoves:Math.min(local.syncedMoves??remoteGame.syncedMoves??0,remoteGame.moves.length),syncedEvents:remoteGame.events.length}
    })
    const guestGames=localGames.filter(game=>game.serverVersion===undefined&&!remoteIds.has(game.id))
    savedGames.value=[...merged,...guestGames].sort((a,b)=>b.updatedAt.localeCompare(a.updatedAt));persistGames()
    return await migrateLocalGames()
  }catch{message.value='云端棋局加载失败，请稍后重试';return empty}
}
async function loadAuthState(){
  try{authMethods.value=await getAuthMethods()}catch{authMethods.value={email:true,oidc:false,email_verification_required:false}}
  try{privacyConfig.value=await getPrivacyConfig()}catch{}
  try{currentUser.value=await getMe()}catch{currentUser.value=null}
}
async function submitEmailAuth(){
  emailAuthBusy.value=true;emailAuthError.value='';emailAuthNotice.value=''
  try{
    if(emailAuthTab.value==='register'){
      if(!privacyAccepted.value){emailAuthError.value='请先阅读并同意隐私政策';return}
      await registerEmail({email:emailAuthEmail.value,password:emailAuthPassword.value,display_name:emailAuthDisplayName.value.trim()||undefined,accept_privacy:true,policy_version:privacyConfig.value.policy_version})
      emailAuthTab.value='login';emailAuthPassword.value='';emailAuthNotice.value=authMethods.value.email_verification_required?'验证邮件已发送，请先打开邮件中的链接，再登录。':'注册成功，请直接登录。';return
    }
    if(emailAuthTab.value==='forgot'){
      await forgotPassword(emailAuthEmail.value);emailAuthNotice.value='如果该邮箱存在，重置链接已发送。';return
    }
    if(emailAuthTab.value==='reset'){
      await resetPassword(emailActionToken.value,emailAuthPassword.value);emailAuthTab.value='login';emailAuthPassword.value='';emailActionToken.value='';emailAuthNotice.value='密码已重置，请重新登录。';return
    }
    await loginEmail({email:emailAuthEmail.value,password:emailAuthPassword.value})
    currentUser.value=await getMe();emailAuthOpen.value=false;emailAuthPassword.value='';const migration=await loadServerGames();message.value=migration.migrated?`登录成功，已将 ${migration.migrated} 局本地棋局保存到账号${migration.failed?`，另有 ${migration.failed} 局待重试`:''}`:migration.failed?`登录成功，${migration.failed} 局本地棋局暂未同步，请稍后重试`:'登录成功'
  }catch(error){emailAuthError.value=error instanceof Error?error.message:'邮箱登录失败'}finally{emailAuthBusy.value=false}
}
async function resendVerification(){emailAuthBusy.value=true;emailAuthError.value='';try{await requestEmailVerification(emailAuthEmail.value);emailAuthNotice.value='如果该邮箱尚未验证，验证邮件已发送。'}catch(error){emailAuthError.value=error instanceof Error?error.message:'发送失败'}finally{emailAuthBusy.value=false}}
async function acceptCurrentPrivacy(){privacyBusy.value=true;try{await acceptPrivacy(privacyConfig.value.policy_version);privacyAccepted.value=false;const migration=await loadServerGames();message.value=migration.migrated?`隐私政策已确认，已将 ${migration.migrated} 局本地棋局保存到账号${migration.failed?`，另有 ${migration.failed} 局待重试`:''}`:migration.failed?`隐私政策已确认，${migration.failed} 局本地棋局暂未同步，请稍后重试`:'隐私政策已确认'}catch(error){message.value=error instanceof Error?error.message:'确认失败'}finally{privacyBusy.value=false}}
async function restoreAccount(){try{await cancelDeletion();await loadServerGames();message.value='账号删除已取消'}catch(error){message.value=error instanceof Error?error.message:'取消删除失败'}}
async function processEmailAction(){const params=new URLSearchParams(window.location.hash.slice(1));const action=params.get('email_action'),token=params.get('token');if(!token||!action)return;window.history.replaceState({},'',window.location.pathname);if(action==='reset'){emailActionToken.value=token;emailAuthTab.value='reset';emailAuthOpen.value=true;return}if(action==='verify'){try{await verifyEmail(token);message.value='邮箱验证成功，请登录';emailAuthTab.value='login';emailAuthOpen.value=true}catch(error){message.value=error instanceof Error?error.message:'验证链接无效'}}}
async function logoutCurrent(){await logout();currentUser.value=null;savedGames.value=[];currentGameId.value=null;message.value='已退出登录'}
function persistGames(){try{localStorage.setItem(GAME_STORAGE_KEY,JSON.stringify(savedGames.value))}catch{message.value='浏览器存储不可用，棋局仅保留在当前页面'}}
function currentEngineSettings():PersistedEngineSettings{return{difficulty:difficulty.value,allow_suboptimal:allowSuboptimal.value,depth:depth.value,movetime_ms:movetime.value,threads:threads.value,hash_mb:hashMb.value}}
function createGameRecord(id:string, startedAt:string, updatedAt:string, name=''):SavedGame{return{id,name,startedAt,updatedAt,baseFen:baseFen.value,moves:[...history.value],events:[...gameEvents.value],side:side.value,depth:depth.value,movetime:movetime.value,multipv:analysisMultiPv.value,difficulty:difficulty.value,difficultySettings:{...currentEngineSettings(),hintLimit:null},hintSettings:{difficulty:hintDifficulty.value,depth:hintDepth.value,movetime_ms:hintMovetime.value,multipv:hintMultiPv.value,showCandidates:showHintCandidates.value},hintsUsed:hintUsed.value,reviewCache:cachedReviewFor(currentReviewSnapshot.value)}}
function saveCurrentGame(){
  if(!currentGameId.value)return
  const now=new Date().toISOString(),existing=savedGames.value.find(g=>g.id===currentGameId.value)
  if(!history.value.length&&!gameEvents.value.length&&!existing)return
  const record=createGameRecord(currentGameId.value,existing?.startedAt??now,now,existing?.name??'')
  if(existing)Object.assign(existing,record);else savedGames.value.unshift(record)
  savedGames.value.sort((a,b)=>b.updatedAt.localeCompare(a.updatedAt));persistGames();if(existing)void syncCurrentGame(existing)
}
function openSaveGameDialog(){
  if(setupMode.value||status.value==='thinking')return
  saveGameName.value='';saveNameError.value='';saveNameDialogOpen.value=true
}
function cancelSaveGame(){saveNameDialogOpen.value=false;saveGameName.value='';saveNameError.value=''}
function savePositionAsGame(name:string){
  const now=new Date().toISOString(),id=`${now}-${Math.random().toString(36).slice(2,8)}`
  const record=createGameRecord(id,now,now,name);savedGames.value.unshift(record);currentGameId.value=id;if(record.reviewCache)record.reviewCache.snapshotKey=reviewSnapshotKey(currentReviewSnapshot.value);savedGames.value.sort((a,b)=>b.updatedAt.localeCompare(a.updatedAt));persistGames();message.value=`棋局“${name}”已保存，可在“棋局”中继续或重开`
  void createGame({name,initial_fen:baseFen.value,engine_settings:currentEngineSettings(),events:record.events as PersistedGameEvent[]}).then(remote=>{record.id=remote.id;record.serverVersion=remote.version;record.syncedMoves=0;record.syncedEvents=remote.events.length;currentGameId.value=remote.id;if(record.reviewCache)record.reviewCache.snapshotKey=reviewSnapshotKey(currentReviewSnapshot.value);persistGames();void syncCurrentGame(record)}).catch(()=>{})
}
async function syncCurrentGame(game:SavedGame){
  if(!game.serverVersion&&game.serverVersion!==0)return
  let version=game.serverVersion??0
  const start=game.syncedMoves??0
  for(const uci of game.moves.slice(start)){const remote=await appendGameMove(game.id,{expected_version:version,uci,engine_settings:{difficulty:game.difficulty,allow_suboptimal:game.difficultySettings.allow_suboptimal,depth:game.difficultySettings.depth,movetime_ms:game.difficultySettings.movetime_ms,threads:game.difficultySettings.threads,hash_mb:game.difficultySettings.hash_mb}});version=remote.version;game.syncedMoves=(game.syncedMoves??0)+1}
  if((game.syncedEvents??0)<game.events.length){const remote=await updateGameEvents(game.id,{expected_version:version,events:game.events as PersistedGameEvent[]});game.syncedEvents=remote.events.length}
  game.serverVersion=version;persistGames()
}
function confirmSaveGame(){const name=saveGameName.value.trim();if(!name){saveNameError.value='请输入棋局名称';return}savePositionAsGame(name.slice(0,60));cancelSaveGame()
}
function rebuildPosition(fen:string,moves:string[]){let next=parseFen(fen);for(const move of moves)next=applyMove(next,fromUci(move.slice(0,2)),fromUci(move.slice(2)));return next}
function rebuildPositionHistory(fen:string,moves:string[]){const positions=[parseFen(fen)];for(const move of moves)positions.push(applyMove(positions[positions.length-1],fromUci(move.slice(0,2)),fromUci(move.slice(2))));return positions}
function perpetualRuleForMove(move:string,moves=history.value){try{const positions=rebuildPositionHistory(baseFen.value,moves);const current=positions[positions.length-1];positions.push(applyMove(current,fromUci(move.slice(0,2)),fromUci(move.slice(2))));const check=perpetualCheckSide(positions,[...moves,move]);if(check)return {side:check,kind:'长将'} as const;const chase=perpetualChaseSide(positions,[...moves,move]);return chase?{side:chase,kind:'长捉'} as const:null}catch{return null}}
function perpetualCheckForMove(move:string,moves=history.value){return perpetualRuleForMove(move,moves)?.side??null}
function perpetualCheckMessage(rule:{side:'red'|'black';kind:'长将'|'长捉'}|null){return rule?`${rule.side==='red'?'红方':'黑方'}连续${rule.kind}，违反棋规，不能执行该着法`:''}
function useSavedGame(view:SavedGameView,replay=false){
  const game=savedGames.value.find(item=>item.id===view.id);if(!game)return
  try{
    position.value=rebuildPosition(game.baseFen,replay?[]:game.moves);baseFen.value=game.baseFen;history.value=replay?[]:[...game.moves];gameEvents.value=replay?[]:[...(game.events??[])] as GameEvent[];futureMoves.value=[];redoBatchSize.value=null;currentGameId.value=replay?null:game.id
    side.value=game.side;difficulty.value=game.difficulty;allowSuboptimal.value=game.difficultySettings.allow_suboptimal;depth.value=game.difficultySettings.depth;movetime.value=game.difficultySettings.movetime_ms;threads.value=game.difficultySettings.threads;hashMb.value=game.difficultySettings.hash_mb;analysisMultiPv.value=game.multipv??3;hintDifficulty.value=game.hintSettings?.difficulty??'regular';hintDepth.value=game.hintSettings?.depth??depth.value;hintMovetime.value=game.hintSettings?.movetime_ms??movetime.value;hintMultiPv.value=game.hintSettings?.multipv??3;showHintCandidates.value=game.hintSettings?.showCandidates??true;hintUsed.value=replay?0:game.hintsUsed
    fenInput.value=toFen(position.value);selected.value=null;analysis.value=null;setupMode.value=false;setupDraft.value=null;setupTool.value='move';setupSelectedSquare.value=null;setupHistory.value=[];setupErrors.value=[];clearStudy();clearReview();message.value=replay?'已从棋局起始局面重新开始':'棋局已载入，可以继续';tab.value='duel';if(!replay)void startQuickReview()
  }catch{message.value='棋局记录损坏，无法载入'}
}
function removeGame(view:SavedGameView){const game=savedGames.value.find(item=>item.id===view.id);savedGames.value=savedGames.value.filter(g=>g.id!==view.id);if(currentGameId.value===view.id)currentGameId.value=null;persistGames();if(game?.serverVersion!==undefined)void deleteGame(view.id).catch(()=>{})}
function resetGame(){saveCurrentGame();currentGameId.value=null;gameEvents.value=[];baseFen.value=START_FEN;position.value=parseFen(START_FEN);fenInput.value=START_FEN;history.value=[];futureMoves.value=[];redoBatchSize.value=null;selected.value=null;analysis.value=null;setupMode.value=false;setupDraft.value=null;setupTool.value='move';setupSelectedSquare.value=null;setupHistory.value=[];setupErrors.value=[];hint.value={move:null,label:null};hintCandidates.value=[];coachContext.value='';clearStudy();clearReview();planAnalysis.value=null;message.value='新局已开始';}
function loadFen(){try{saveCurrentGame();position.value=parseFen(fenInput.value);baseFen.value=toFen(position.value);fenInput.value=baseFen.value;history.value=[];gameEvents.value=[];futureMoves.value=[];redoBatchSize.value=null;currentGameId.value=null;selected.value=null;analysis.value=null;setupMode.value=false;setupDraft.value=null;setupTool.value='move';setupSelectedSquare.value=null;setupHistory.value=[];setupErrors.value=[];coachContext.value='';clearStudy();clearReview();message.value='局面已加载'}catch(error){message.value=error instanceof Error?error.message:'FEN 无效'}}
async function undo(){
  if(!canUndo.value)return
  const originalMoves=[...history.value], count=undoSteps.value, result=undoMoves(originalMoves,count,futureMoves.value)
  const steps=Array.from({length:count},(_,index)=>originalMoves.slice(0,originalMoves.length-index-1))
  replayBusy.value=true;selected.value=null;analysis.value=null;coachContext.value='';clearStudy();clearReview()
  try{
    await playMoveSteps(steps,moves=>{
      position.value=rebuildPosition(baseFen.value,moves)
      history.value=moves
      futureMoves.value=[...originalMoves.slice(moves.length),...result.future.slice(count)]
      fenInput.value=toFen(position.value)
    })
    position.value=rebuildPosition(baseFen.value,result.moves);fenInput.value=toFen(position.value);history.value=result.moves;futureMoves.value=result.future;redoBatchSize.value=count
    gameEvents.value.push(createUndoEvent(originalMoves,count,fenInput.value));saveCurrentGame();message.value='已撤回走法'
  }finally{replayBusy.value=false}
}
async function redo(){
  if(!canRedo.value)return
  const originalMoves=[...history.value], originalFuture=[...futureMoves.value], count=redoSteps.value, result=advanceMoves(originalMoves,originalFuture,count)
  const steps=Array.from({length:count},(_,index)=>[...originalMoves,...originalFuture.slice(0,index+1)])
  replayBusy.value=true;selected.value=null;analysis.value=null;coachContext.value='';clearStudy();clearReview()
  try{
    await playMoveSteps(steps,moves=>{
      position.value=rebuildPosition(baseFen.value,moves)
      history.value=moves
      futureMoves.value=originalFuture.slice(moves.length-originalMoves.length)
      fenInput.value=toFen(position.value)
    })
    history.value=result.moves;futureMoves.value=result.future;position.value=rebuildPosition(baseFen.value,result.moves);fenInput.value=toFen(position.value);saveCurrentGame();message.value='已恢复走法'
  }finally{replayBusy.value=false}
}
function clickSquare(row:number,col:number){
  if(setupMode.value){placeSetupPiece(row,col);return}
  if(!canHumanMove.value){message.value=studyMode.value?'浏览局面中，请返回当前对局后落子':side.value==='watch'?'观战模式不能手动落子':'等待 Pikafish 完成应手';return}
  const piece=position.value.board[row][col]
  if(selected.value&&legal.value.some(([r,c])=>r===row&&c===col)){
    const move=`${toUci(...selected.value)}${toUci(row,col)}`
    const offender=perpetualRuleForMove(move)
    if(offender){selected.value=null;message.value=perpetualCheckMessage(offender);return}
    position.value=applyMove(position.value,selected.value,[row,col]);history.value.push(move);futureMoves.value=[];redoBatchSize.value=null;selected.value=null;analysis.value=null;hint.value={move:null,label:null};hintCandidates.value=[];coachContext.value='';clearReview();clearStudy();ensureGame();saveCurrentGame();message.value=`${move} 已落子`
    const engineTurn=side.value!=='watch'&&side.value!==(position.value.redToMove?'red':'black')
    if(engineTurn&&engineReady.value)void askEngine(true);else if(engineTurn)message.value+='；当前为手动模式'
  }else if(piece!=='.'&&(piece===piece.toUpperCase())===position.value.redToMove)selected.value=[row,col]
  else selected.value=null
}
function ensureGame(){if(!currentGameId.value)currentGameId.value=new Date().toISOString()}
function enginePayload(multipv:number,deep=depth.value,time=movetime.value){return{fen:baseFen.value,moves:[...history.value],depth:deep,movetime_ms:time,multipv,threads:threads.value,hash_mb:hashMb.value}}
function analysisPayload(multipv:number){
  const prefix=selectedPly.value===null?history.value:history.value.slice(0,selectedPly.value-1)
  return{fen:baseFen.value,moves:[...prefix],depth:depth.value,movetime_ms:movetime.value,multipv,threads:threads.value,hash_mb:hashMb.value}
}
function terminalMessage(result:Analysis){
  if(!result.terminal_status)return null
  const side=position.value.redToMove?'红方':'黑方'
  return result.terminal_status==='checkmate'?`${side}被将死，棋局结束`:`${side}困毙，棋局结束`
}
async function askEngine(playMove=false){
  if(playMove&&gameTerminal.value){message.value=`${position.value.redToMove?'红方':'黑方'}${gameTerminal.value==='checkmate'?'被将死':'困毙'}，棋局结束`;return}
  if(!engineReady.value){message.value='Pikafish 未配置；可继续手动走子';return}
  const turnStartedAt=Date.now()
  status.value='thinking';message.value='Pikafish 思考中…'
  try{const payload=enginePayload(playMove?1:analysisMultiPv.value);const result=playMove?await engineMove({...payload,difficulty:difficulty.value,allow_suboptimal:allowSuboptimal.value,game_id:currentGameId.value??baseFen.value,ply:history.value.length}):await analyze(payload);if(playMove)await waitForMinimumElapsed(turnStartedAt,ENGINE_MOVE_MINIMUM_DELAY_MS);else analysis.value=result;status.value='idle';const terminal=terminalMessage(result);if(terminal){message.value=terminal;return}if(playMove&&result.bestmove!=='0000'){const offender=perpetualRuleForMove(result.bestmove);if(offender){message.value=perpetualCheckMessage(offender);return}const from=fromUci(result.bestmove.slice(0,2)),to=fromUci(result.bestmove.slice(2));position.value=applyMove(position.value,from,to);history.value.push(result.bestmove);futureMoves.value=[];redoBatchSize.value=null;fenInput.value=toFen(position.value);saveCurrentGame();message.value=`${presets[difficulty.value].label}：Pikafish 走 ${result.bestmove}`}else message.value=`已分析 ${result.lines.length} 条候选着法`}catch(error){status.value='error';message.value=error instanceof Error?error.message:'分析失败'}
}
async function analyzeCurrentView(){
  if(!engineReady.value){message.value='Pikafish 未配置，无法进行引擎分析';return}
  status.value='thinking';
  try{const result=await analyze(analysisPayload(analysisMultiPv.value));analysis.value=result;status.value='idle';const terminal=terminalMessage(result);message.value=terminal??(result.filter_summary?.rejected.length?`已过滤 ${result.filter_summary.rejected.length} 条不合法或违反棋规的候选着法`:`已分析 ${result.lines.length} 条候选着法`)}
  catch(error){status.value='error';message.value=error instanceof Error?error.message:'分析失败'}
}
function hintScore(score: Analysis['lines'][number]['score']){if(!score)return '无分值';if(score.type==='mate')return score.value>0?`将死 ${score.value} 步`:`被将死 ${Math.abs(score.value)} 步`;return `${score.value>0?'+':''}${score.value} cp`}
function planScore(score: PlanAnalysis['best']['score']){if(!score)return '无可靠分值';if(score.type==='mate')return score.value>0?`将死 ${score.value} 步`:`被将死 ${Math.abs(score.value)} 步`;return `${score.value>0?'+':''}${score.value} cp`}
function waitForHintReveal(){return new Promise<void>(resolve=>window.setTimeout(resolve,220))}
async function requestHint(){if(!canRequestHint.value)return;status.value='thinking';hint.value={move:null,label:null};hintCandidates.value=[];try{const result=await analyze(enginePayload(showHintCandidates.value?hintMultiPv.value:1,hintDepth.value,hintMovetime.value));const terminal=terminalMessage(result);if(terminal){status.value='idle';message.value=terminal;return}const candidates=collectHintCandidates(result.lines,result.bestmove,undefined,move=>({rank:1,move,label:describeUci(position.value,move),score:result.score,depth:result.depth,pv:result.pv}));if(!candidates.length){status.value='idle';message.value='引擎没有返回可执行候选着法';return}if(showHintCandidates.value){for(let index=0;index<candidates.length;index+=1){if(index>0)await waitForHintReveal();hintCandidates.value=[...hintCandidates.value,candidates[index]];message.value=`正在显示第 ${index+1}/${candidates.length} 条候选`;}}const candidate=candidates[0];hint.value={move:candidate.move,label:candidate.label};gameEvents.value.push(createHintEvent(history.value,toFen(position.value),candidates.map(({move,label,score})=>({move,label,score}))));saveCurrentGame();status.value='idle';message.value=result.filter_summary?.rejected.length?`提示：${hint.value.label}（已过滤 ${result.filter_summary.rejected.length} 条候选）`:showHintCandidates.value?`提示：${hint.value.label}（已比较 ${candidates.length} 条候选）`:`最优提示：${hint.value.label}`}catch(error){status.value='error';message.value=error instanceof Error?error.message:'提示失败'}}
async function analyzePlanNow(){if(!planIdea.value.trim()||!planMove.value.trim()||!validSettings.value)return;planBusy.value=true;try{planAnalysis.value=await analyzePlan({...analysisPayload(1),idea:planIdea.value.trim(),move:planMove.value.trim()})}catch(error){message.value=error instanceof Error?error.message:'思路分析失败'}finally{planBusy.value=false}}
async function runReview(){
  if(history.value.length>120){reviewError.value='棋谱超过 120 个半回合，请先分段复盘';return}
  reviewBusy.value=true;reviewError.value='';clearStudy()
  try{const persisted=savedGames.value.find(game=>game.id===currentGameId.value&&game.serverVersion!==undefined);reviewResult.value=persisted?await persistReview(persisted.id,{fen:baseFen.value,moves:[...history.value],depth:8,movetime_ms:350,threads:1,hash_mb:128}):await review({fen:baseFen.value,moves:[...history.value],depth:8,movetime_ms:350,threads:1,hash_mb:128});selectedPly.value=null;message.value='复盘完成'}catch(error){reviewError.value=error instanceof Error?error.message:'复盘失败'}finally{reviewBusy.value=false}
}
function selectReview(item:ReviewItem){selectedPly.value=item.ply;selectedLine.value=null;selectedMove.value=null;analysis.value=null;studyMode.value=true}
function selectCandidate(move:string){selectedLine.value=analysis.value?.lines.find(line=>line.move===move)?.rank??null;selectedMove.value=move;studyMode.value=true;selectedPly.value=null;tab.value='analysis'}
function askCoachAboutReview(item:ReviewItem){selectReview(item);coachContext.value=`复盘第 ${item.ply} 半回合，${item.side==='red'?'红方':'黑方'}走 ${item.label}。引擎推荐 ${item.best_label??'未知'}，损失 ${item.loss_cp===null?'无法可靠换算':`${item.loss_cp} cp`}，分类 ${item.grade}。主变化：${item.pv.join(' ')}`;tab.value='coach'}
async function refreshOpenings(){try{const response=await getOpenings({fen:baseFen.value,moves:liveMoves.value});openings.value=response.matches}catch{openings.value=[]}}
async function sendCoach(question:string){
  const prior=coachMessages.value.slice(-20);coachMessages.value=[...coachMessages.value,{role:'user',content:question}];coachBusy.value=true;coachUnavailable.value=''
  try{const game=coachPosition(baseFen.value,liveFen.value,liveMoves.value,!setupMode.value&&selectedPly.value===null);const result=await coachChat({question,...game,messages:prior,context:coachContext.value});if(result.ai_available){llmLastError.value='';coachMessages.value.push({role:'assistant',content:result.answer})}else{llmLastError.value=result.ai_message??'AI 教练暂不可用';coachUnavailable.value=llmLastError.value}}catch(error){llmLastError.value=error instanceof Error?error.message:'AI 教练暂不可用';coachUnavailable.value=llmLastError.value}finally{coachBusy.value=false}
}
function askNextStep(){const session=nextStepSession();coachMessages.value=session.messages;coachContext.value=session.context;coachUnavailable.value='';void sendCoach(session.question)}
async function refreshHealth(){try{health.value=await getHealth();healthError.value='';lastHealthCheck.value=new Date()}catch(error){healthError.value=error instanceof Error?error.message:'后端不可用';health.value=null;lastHealthCheck.value=new Date();message.value=healthError.value}}
async function restartEngine(){health.value=await resetEngine();message.value=health.value.engine_ready?'引擎已重启':health.value.error??'引擎未配置'}
function exportMoves(){void navigator.clipboard?.writeText(history.value.join(' '));message.value='走法已复制'}
function setTab(next:Tab){tab.value=next;if(next==='analysis')void refreshOpenings();if(next==='games'&&history.value.length)void startQuickReview()}
watch(side,value=>{if(value==='black'&&position.value.redToMove&&!history.value.length&&engineReady.value)void askEngine(true)})
watch(history,()=>{void refreshOpenings()})
watch([gameTerminal,()=>reviewSnapshotKey(currentReviewSnapshot.value),engineReady,()=>status.value],()=>{
  if(!gameTerminal.value||setupMode.value||!history.value.length)return
  message.value=`${position.value.redToMove?'红方':'黑方'}${gameTerminal.value==='checkmate'?'被将死':'困毙'}，棋局结束`
  if(quickReviewReason.value)return
  const key=reviewSnapshotKey(currentReviewSnapshot.value)
  if(key===lastAutomaticReview)return
  lastAutomaticReview=key
  if(!quickReviewStale.value&&(quickReview.result.value||quickReview.busy.value))return
  void startQuickReview()
})
watch([difficulty,allowSuboptimal,depth,movetime,threads,hashMb,hintDifficulty,hintDepth,hintMovetime,hintMultiPv,showHintCandidates],()=>saveEngineSettings())
watch(boardTheme,value=>{try{localStorage.setItem(BOARD_THEME_STORAGE_KEY,value)}catch{}})
onMounted(()=>{readEngineSettings();readBoardTheme();readSavedGames();void loadAuthState().then(loadServerGames);void processEmailAction();void refreshHealth();void refreshOpenings();healthRefreshTimer=window.setInterval(()=>void refreshHealth(),15_000)})
onUnmounted(()=>{if(healthRefreshTimer!==undefined)window.clearInterval(healthRefreshTimer);quickReview.invalidate()})
</script>

<template>
  <main class="shell">
    <header class="topbar"><div><p class="eyebrow">PIKAFISH XIANGQI COACH</p><h1>AI 象棋教练</h1><p class="subtitle">对弈、分析、复盘与教练问答集中在一个工作台。</p></div><div class="topbar-actions"><div class="health" :class="health?.engine_ready?'ok':'warn'"><span class="dot"/>{{ engineLabel }}<button class="icon-button" title="重启引擎" @click="restartEngine">↻</button></div><template v-if="!currentUser"><button v-if="authMethods.oidc" class="secondary compact" @click="beginOidcLogin">OIDC 登录</button><button v-if="authMethods.email" class="secondary compact" @click="emailAuthOpen=true;emailAuthTab='login'">邮箱登录</button></template><span v-else class="user-label">{{ currentUser.display_name || '已登录' }} <button v-if="currentUser.status==='deletion_pending'" class="secondary compact" @click="restoreAccount">取消删除</button> <button class="secondary compact" @click="logoutCurrent">退出</button></span></div></header>
    <section v-if="currentUser?.status==='active'&&currentUser.privacy_accepted===false" class="privacy-banner"><strong>请确认隐私政策</strong><span>保存棋局前需要同意当前版本（{{ privacyConfig.policy_version }}）。</span><a href="/privacy.html" target="_blank" rel="noopener">阅读隐私政策</a><button class="primary compact" :disabled="privacyBusy" @click="acceptCurrentPrivacy">同意并继续</button></section>
    <section class="service-status card" aria-label="服务状态"><div class="service-status-head"><div><h2>服务状态</h2><p class="help">自动检查后端和本地引擎；大模型状态来自配置与最近一次请求。</p></div><button class="secondary compact" @click="refreshHealth">刷新状态</button></div><div class="service-grid"><div v-for="service in serviceItems" :key="service.key" class="service-item"><span class="service-dot" :class="service.state"/><span>{{ service.label }}</span><strong>{{ service.text }}</strong></div></div><p v-if="healthError" class="service-error help">{{ healthError }}</p><p v-else-if="health?.error" class="service-error help">{{ health.error }}</p><p v-if="llmLastError" class="service-error help">大模型：{{ llmLastError }}</p><p class="service-time help">{{ healthCheckedLabel }}</p></section>
    <section class="workspace">
      <div class="board-column"><div class="board-panel"><label class="board-theme-picker">棋盘风格<select v-model="boardTheme"><option value="classic">经典</option><option value="high-contrast">黑白高对比</option><option value="wood">立体木纹</option></select></label><BoardView :position="displayPosition" :interactive="canHumanMove" :theme="boardTheme" :setup-selected-square="setupSelectedSquare" :last-move="displayedLastMove" :highlight-move="highlightMove" @square="clickSquare"/><div class="turn-line"><span>当前轮次：<b>{{ displayPosition.redToMove?'红方':'黑方' }}</b></span><span>{{ studyMode?'浏览模式':message }}</span></div><button v-if="studyMode" class="return-live" @click="clearStudy">返回当前对局</button></div><div class="move-strip"><strong>本局棋谱</strong><span>{{ history.length?history.map((move,index)=>`${Math.ceil((index+1)/2)}${index%2===0?'.':''} ${move}`).join('　'):'尚未落子' }}</span><button @click="exportMoves">复制</button></div></div>
      <section class="work-panel"><nav class="tabs" aria-label="功能分类"><button v-for="item in tabs" :key="item.id" :class="{active:tab===item.id}" @click="setTab(item.id)">{{ item.label }}<span v-if="item.id==='games'" class="tab-count">{{ savedGames.length }}</span></button></nav>
        <article v-if="(tab==='duel'||tab==='review'||tab==='games') && quickReview.snapshot.value" class="card quick-review-banner"><div><strong>{{ quickReview.busy.value ? '正在生成本局小结…' : quickReview.error.value ? '本局小结暂未完成' : `本局小结 · ${quickReview.moments.value.length} 个关键时刻` }}</strong><p class="help">{{ quickReviewStale ? '上次复盘后棋局已变化，可按当前进度重新分析。' : quickReview.error.value || '只看值得回看的一步，不给自己增加负担。' }}</p></div><div class="quick-review-actions"><button :disabled="!!quickReviewReason" @click="openReview()">{{ quickReviewStale ? '复盘当前进度' : '查看小结' }}</button><button v-if="quickReview.result.value" class="secondary" :disabled="!!quickReviewReason || quickReview.busy.value" @click="openReview(true)">重新生成</button></div></article>
        <section v-show="tab==='duel'" class="view-stack"><article class="card"><div class="card-title"><div><h2>人机对弈</h2><p class="help">选择适合自己的对手；提示、分析和复盘使用完整棋力。</p></div><span class="pill">{{ status==='thinking'?'THINKING':status==='error'?'ERROR':'READY' }}</span></div><div class="controls"><label>执棋方<select v-model="side"><option value="red">执红</option><option value="black">执黑</option><option value="watch">观战</option></select></label><label>对手水平<select :value="difficulty" @change="applyDifficulty(($event.target as HTMLSelectElement).value as Difficulty)"><option value="companion">轻松陪练</option><option value="beginner">入门练习</option><option value="progress">进阶对手</option><option value="serious">认真对弈</option><option value="full">全力挑战</option><option v-if="difficulty==='custom'" value="custom" disabled>自定义（高级设置中）</option></select></label></div><p class="help">{{ presets[difficulty].label }}：{{ presets[difficulty].description }}。{{ side==='watch'?'观战模式当前不自动运行双方引擎。':'' }}</p><EngineSettings :difficulty="difficulty" :allow-suboptimal="allowSuboptimal" :hint-difficulty="hintDifficulty" :depth="depth" :movetime="movetime" :threads="threads" :hash-mb="hashMb" :max-threads="maxThreads" :hint-depth="hintDepth" :hint-movetime="hintMovetime" :hint-multi-pv="hintMultiPv" :show-hint-candidates="showHintCandidates" @save="saveEngineSettings(true)" @update:difficulty="applyDifficulty($event)" @update:allow-suboptimal="allowSuboptimal=$event" @update:hint-difficulty="applyHintDifficulty($event)" @update:depth="depth=$event" @update:movetime="movetime=$event" @update:threads="threads=$event" @update:hash-mb="hashMb=$event" @update:hint-depth="hintDepth=$event" @update:hint-movetime="hintMovetime=$event" @update:hint-multipv="hintMultiPv=$event" @update:show-hint-candidates="setShowHintCandidates($event)"/><div class="button-row"><button class="hint-button" :disabled="!canRequestHint" @click="requestHint">提示一步</button><button :disabled="!!quickReviewReason" :title="quickReviewReason || '复盘当前已完成的棋谱'" @click="openReview()">复盘</button><button :disabled="setupMode||status==='thinking'" @click="openSaveGameDialog">保存为新棋局</button><button @click="resetGame">新局</button><button :disabled="!canUndo" @click="undo">悔棋</button><button :disabled="!canRedo" title="恢复已撤回的走法" @click="redo">前进</button><button @click="exportMoves">复制走法</button></div><p v-if="quickReviewReason" class="help">复盘：{{ quickReviewReason }}</p><p v-if="hint.move" class="hint-result">建议：<strong>{{ hint.label }}</strong>（{{ hint.move }}）</p><div v-if="hintCandidates.length" class="hint-candidates"><div class="hint-candidates-title">候选着法 <span>{{ hintCandidates.length }}/{{ hintMultiPv }}</span></div><div v-for="(candidate,index) in hintCandidates" :key="`${candidate.rank}-${candidate.move}`" class="hint-candidate" :class="{ best: index===0 }"><strong>{{ index + 1 }}. {{ index===0?'最佳 · ':'' }}{{ candidate.label }}</strong><span>{{ hintScore(candidate.score) }}</span></div></div></article><article class="card"><div class="card-title"><h2>棋局状态</h2></div><p class="help">{{ message }}</p><p class="help">已走 {{ history.length }} 个半回合 · {{ engineReady?'Pikafish 已连接':'未配置引擎，当前可手动走子' }}</p></article></section>
        <AnalysisView v-show="tab==='analysis'" :analysis="analysis" :position="displayPosition" :busy="status==='thinking'" :multipv="analysisMultiPv" :fen="fenInput" :openings="openings" :selected-line="selectedLine" @analyze="analyzeCurrentView" @update:multipv="analysisMultiPv=$event" @update:fen="fenInput=$event" @load-fen="loadFen" @select-line="selectCandidate" @coach="coachContext=$event;tab='coach'"/>
        <section v-show="tab==='analysis'" class="card plan-analysis"><div class="card-title"><div><h2>比较我的思路</h2><p class="help">输入计划和具体着法，比较与引擎推荐的差异。</p></div></div><label class="plan-label">我的计划<textarea v-model="planIdea" rows="2" maxlength="1200"/></label><label class="plan-label">准备走的着法<input v-model="planMove" placeholder="炮二平五 或 h2e2" maxlength="40"/></label><button class="secondary" :disabled="planBusy||!planIdea.trim()||!planMove.trim()" @click="analyzePlanNow">{{ planBusy?'分析中…':'比较着法' }}</button><template v-if="planAnalysis"><p class="help">当前视角：{{ planAnalysis.perspective==='black'?'黑方':'红方' }}；引擎最佳：{{ planAnalysis.best.label }}（{{ planScore(planAnalysis.best.score) }}）；你的着法：{{ planAnalysis.proposed.label }}（{{ planScore(planAnalysis.proposed.score) }}）。<template v-if="planAnalysis.comparison_status==='cp'">差值 {{ planAnalysis.score_difference_cp??'—' }} cp。</template><template v-else-if="planAnalysis.comparison_status==='mate'">双方结果包含将杀，差值不换算为 cp。</template></p><p v-if="planAnalysis.ai_message" class="help">{{ planAnalysis.ai_message }}</p><template v-if="planAnalysis.explanation"><p>{{ planAnalysis.explanation.engine_assessment }}</p><p>{{ planAnalysis.explanation.suggestion }}</p></template></template></section>
        <ReviewView v-show="tab==='review'" :side="side" :result="reviewResult" :busy="reviewBusy" :error="reviewError" :selected-ply="selectedPly" @start="runReview" @select="selectReview" @coach="askCoachAboutReview"/>
        <CoachView v-show="tab==='coach'" :messages="coachMessages" :busy="coachBusy" :unavailable="coachUnavailable" @send="sendCoach" @next-step="askNextStep"/>
        <GamesView v-show="tab==='games'" :games="savedGames" @continue="useSavedGame($event)" @replay="useSavedGame($event,true)" @remove="removeGame"/>
        <SetupControls v-show="tab==='duel'" :active="setupMode" :position="setupDraft" :selected-tool="setupTool" :can-undo="setupHistory.length > 0" :red-to-move="recognitionUi.pending ? recognitionPosition?.redToMove ?? setupDraft?.redToMove ?? position.redToMove : setupDraft?.redToMove ?? position.redToMove" :errors="setupErrors" :recognizing-image="recognitionBusy" :recognition-error="recognitionError" :recognition-preview-url="recognitionPreviewUrl" :recognition-piece-count="recognitionPieceCount" :recognition-pieces="recognitionPieces" :recognition-applied="recognitionApplied" :recognition-warnings="recognitionWarnings" :can-apply-recognition="canApplyRecognition" @start="startSetup" @cancel="cancelSetup" @undo="undoSetup" @clear="clearSetupBoard" @reset="resetSetupBoard" @finish="finishSetup" @update:selected-tool="setupTool=$event" @update:red-to-move="setSetupTurn($event)" @recognize-image="recognizeSetup" @cancel-recognition="cancelRecognition" @apply-recognition="applyRecognizedPosition" @discard-recognition="clearRecognition"/>
      </section>
    </section>
    <ReviewDialog v-if="reviewDialogOpen && quickReview.snapshot.value && quickReview.board.value" :snapshot="quickReview.snapshot.value" :result="quickReview.result.value" :busy="quickReview.busy.value" :error="quickReview.error.value" :board="quickReview.board.value" :selected="quickReview.selected.value" :moments="quickReview.moments.value" :messages="quickReview.messages.value" :chat-busy="quickReview.chatBusy.value" :chat-error="quickReview.chatError.value" :stale="quickReviewStale" :theme="boardTheme" :retry-reason="quickReviewReason" @close="reviewDialogOpen=false" @retry="openReview(true)" @select="quickReview.select" @ask="quickReview.ask"/>
    <div v-if="saveNameDialogOpen" class="modal-backdrop" @click.self="cancelSaveGame">
      <section class="modal-card" role="dialog" aria-modal="true" aria-labelledby="save-game-title">
        <h2 id="save-game-title">保存为新棋局</h2>
        <p class="help">为当前局面设置一个名称，之后可在“棋局”中继续或重开。</p>
        <label class="modal-field">棋局名称<input v-model="saveGameName" maxlength="60" autofocus placeholder="例如：中炮对屏风马" @keyup.enter="confirmSaveGame"></label>
        <p v-if="saveNameError" class="validation">{{ saveNameError }}</p>
        <div class="modal-actions"><button class="secondary compact" @click="cancelSaveGame">取消</button><button class="primary compact" @click="confirmSaveGame">保存棋局</button></div>
      </section>
    </div>
    <div v-if="emailAuthOpen" class="modal-backdrop" @click.self="emailAuthOpen=false">
      <section class="modal-card" role="dialog" aria-modal="true" aria-labelledby="email-auth-title">
        <div class="tabs auth-tabs"><button :class="{active:emailAuthTab==='login'}" @click="emailAuthTab='login';emailAuthError='';emailAuthNotice=''">邮箱登录</button><button :class="{active:emailAuthTab==='register'}" @click="emailAuthTab='register';emailAuthError='';emailAuthNotice=''">注册账号</button></div>
        <h2 id="email-auth-title">{{ emailAuthTab==='login'?'邮箱登录':emailAuthTab==='register'?'注册账号':emailAuthTab==='forgot'?'找回密码':'重置密码' }}</h2>
        <label v-if="emailAuthTab!=='reset'" class="modal-field">邮箱<input v-model.trim="emailAuthEmail" type="email" autocomplete="email" maxlength="320"></label>
        <label v-if="emailAuthTab==='register'" class="modal-field">昵称<input v-model.trim="emailAuthDisplayName" maxlength="120"></label>
        <label v-if="emailAuthTab!=='forgot'" class="modal-field">{{ emailAuthTab==='reset'?'新密码':'密码' }}<input v-model="emailAuthPassword" type="password" :autocomplete="emailAuthTab==='login'?'current-password':'new-password'" maxlength="128"></label>
        <p v-if="emailAuthTab==='register'||emailAuthTab==='reset'" class="help">密码至少 8 位，系统只保存加密哈希。</p>
        <label v-if="emailAuthTab==='register'" class="privacy-check"><input v-model="privacyAccepted" type="checkbox">我已阅读并同意 <a href="/privacy.html" target="_blank" rel="noopener">隐私政策</a>（{{ privacyConfig.policy_version }}）</label>
        <button v-if="emailAuthTab==='login'&&authMethods.email_verification_required" class="text-button" @click="emailAuthTab='forgot';emailAuthError='';emailAuthNotice=''">忘记密码？</button>
        <button v-if="emailAuthTab==='login'&&authMethods.email_verification_required" class="text-button" :disabled="emailAuthBusy" @click="resendVerification">重新发送验证邮件</button>
        <p v-if="emailAuthNotice" class="help">{{ emailAuthNotice }}</p>
        <p v-if="emailAuthError" class="validation">{{ emailAuthError }}</p>
        <div class="modal-actions"><button class="secondary compact" @click="emailAuthOpen=false">取消</button><button class="primary compact" :disabled="emailAuthBusy" @click="submitEmailAuth">{{ emailAuthBusy?'处理中…':emailAuthTab==='login'?'登录':emailAuthTab==='register'?'注册':emailAuthTab==='forgot'?'发送重置链接':'重置密码' }}</button></div>
      </section>
    </div>
  </main>
</template>
