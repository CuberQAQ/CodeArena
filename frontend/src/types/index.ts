/** Shared TypeScript types used across the frontend application. */

// ---------------------------------------------------------------------------
// Auth / User
// ---------------------------------------------------------------------------

export interface UserInfo {
  id: string;
  username: string;
  email: string;
  cf_handle: string | null;
  cf_handle_verified: boolean;
  elo: number;
  pp: number;
  tokens: number;
  is_active: boolean;
  is_admin: boolean;
  created_at: string | null;
  updated_at: string | null;
  last_login_at: string | null;
  avatar_path?: string | null;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface RegisterResponse {
  user: UserInfo;
  tokens: TokenPair;
}

// ---------------------------------------------------------------------------
// API response wrapper (matches backend's unified response format)
// ---------------------------------------------------------------------------

export interface ApiResponse<T = unknown> {
  success: boolean;
  data: T;
  message: string;
}

export interface ApiErrorResponse {
  success: false;
  error: {
    code: string;
    message: string;
  };
  detail?: string;
}

// ---------------------------------------------------------------------------
// Challenge
// ---------------------------------------------------------------------------

export interface OpponentInfo {
  id: string;
  username: string;
  elo: number;
  cf_handle: string | null;
}

export interface MatchResult {
  session_id: string;
  opponent: OpponentInfo;
  status: string;
}

export interface QueueStatus {
  in_queue: boolean;
  matched: boolean;
  session_id: string | null;
  opponent: OpponentInfo | null;
  both_ready: boolean;
}

export interface ProblemInfo {
  contest_id: number;
  index: string;
  name: string;
  rating: number | null;
  tags: string[];
  url: string;
}

export interface ChallengeDetail {
  id: string;
  challenger_id: string;
  opponent_id: string;
  problem_id: string;
  problem_rating: number;
  problem: ProblemInfo | null;
  challenger_solved: boolean;
  opponent_solved: boolean;
  challenger_submissions: number;
  opponent_submissions: number;
  challenger_time: number | null;
  opponent_time: number | null;
  status: string;
  result: string | null;
  is_challenger: boolean;
  elo_change: number | null;
  tokens_earned: number | null;
  opponent_tokens_earned: number | null;
  created_at: string | null;
  completed_at: string | null;
}

export interface StartChallengeResponse {
  session_id: string;
  problem: ProblemInfo;
  status: string;
}

export interface SubmitResultResponse {
  session_id: string;
  solved: boolean;
  status: string;
  settled: boolean;
  result: string | null;
  elo_change: number | null;
  tokens_earned: number | null;
  achievements: AchievementEvent[];
}

export interface QuitChallengeResponse {
  session_id: string;
  status: string;
  elo_change: number | null;
  penalty: number | null;
}

export interface ActiveChallengeInfo {
  id: string;
  problem_id: string;
  problem_name: string | null;
  problem_rating: number;
  created_at: string | null;
  is_challenger: boolean;
  opponent_username: string | null;
  opponent_elo: number | null;
  status: string;
}

// ---------------------------------------------------------------------------
// Training
// ---------------------------------------------------------------------------

export interface TopicProblemInfo {
  problem_id: string;
  contest_id: number;
  index: string;
  name: string;
  rating: number | null;
  tags: string[];
  url: string;
  solved: boolean;
  attempts: number;
  time_spent: number | null;
}

export interface TopicInfo {
  id: string;
  name: string;
  name_zh: string;
  slug: string;
  description: string | null;
  cf_tags: string[];
  display_order: number;
  total_problems: number;
  solved_count: number;
  stars: number;
  melo: number | null;
  shield_active: boolean;
}

export interface TopicDetail extends TopicInfo {
  problems: TopicProblemInfo[];
}

export interface TrainingSessionInfo {
  id: string;
  topic_id: string;
  topic_name: string;
  problems_solved: number;
  total_problems: number;
  streak_count: number;
  status: string;
  created_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  last_solved_rating: number | null;
  streak_tokens_earned: number;
}

export interface SubmitTrainingResponse {
  session_id: string;
  problem_id: string;
  solved: boolean;
  streak_count: number;
  streak_tokens: number;
  total_streak_tokens: number;
  tokens_earned: number;
  elo_change: number | null;
  achievements: AchievementEvent[];
}

export interface TopicProgress {
  topic_id: string;
  topic_name: string;
  slug: string;
  total_problems: number;
  solved_count: number;
  completion_rate: number;
  stars: number;
  total_attempts: number;
  total_time_spent: number;
  melo: number | null;
  shield_active: boolean;
}

export interface TrainingProgress {
  topics: TopicProgress[];
  total_solved: number;
  total_problems: number;
}

export interface AbandonTrainingResponse {
  session_id: string;
  status: string;
  problems_solved: number;
  total_problems: number;
}

// ---------------------------------------------------------------------------
// Training - Recommended & Curated (FR-3.5)
// ---------------------------------------------------------------------------

export interface RecommendedTopic {
  slug: string;
  name: string;
  name_zh: string;
  melo: number | null;
  reason: string;
}

export interface RecommendedProblem {
  problem_id: string;
  contest_id: number;
  index: string;
  name: string;
  rating: number | null;
  tags: string[];
  url: string;
  melo: number;
  search_range: [number, number];
}

export interface CuratedProblemInfo {
  problem_id: string;
  contest_id: number;
  index: string;
  name: string;
  rating: number | null;
  tags: string[];
  url: string;
  solved: boolean;
}

export interface CuratedProblemsResponse {
  problems: CuratedProblemInfo[];
  total: number;
  offset: number;
  limit: number;
}

// ---------------------------------------------------------------------------
// Contest
// ---------------------------------------------------------------------------

export interface TierInfo {
  tier: string;
  name: string;
  div: number | null;
  min_elo: number | null;
  max_elo: number | null;
  duration_minutes: number;
  problem_count: number;
  rating_range: number[] | null;
  eligible: boolean;
  is_rated: boolean;
}

export interface ContestProblemInfo {
  problem_id: string;
  contest_id: number;
  index: string;
  name: string;
  rating: number;
  url: string;
  solved: boolean;
  attempts: number;
  time_spent: number | null;
}

export interface ContestSessionInfo {
  id: string;
  tier: string;
  problems: ContestProblemInfo[];
  total_problems: number;
  problems_solved: number;
  submissions: number;
  time_limit_minutes: number;
  started_at: string | null;
  ended_at: string | null;
  remaining_seconds: number | null;
  end_time: string | null;
  status: string;
  elo_change: number | null;
}

export interface SubmitContestResponse {
  contest_id: string;
  problem_id: string;
  solved: boolean;
  tokens_earned: number;
}

export interface ContestResult {
  id: string;
  tier: string;
  total_problems: number;
  problems_solved: number;
  submissions: number;
  time_limit_minutes: number;
  started_at: string | null;
  ended_at: string | null;
  status: string;
  elo_change: number | null;
  performance_rating: number | null;
  medal: MedalInfo | null;
  problems: ContestProblemInfo[];
  achievements: AchievementEvent[];
  // Extended result fields (backward-compatible, all optional)
  elo_before: number | null;
  elo_after: number | null;
  pp_before: number | null;
  pp_after: number | null;
  pp_change: number | null;
  rank: number | null;
  total_participants: number | null;
  melo_changes: { tag: string; before: number; after: number; change: number }[] | null;
  time_spent_minutes: number | null;
}

export interface ContestHistoryItem {
  id: string;
  tier: string;
  total_problems: number;
  problems_solved: number;
  submissions: number;
  time_limit_minutes: number;
  started_at: string | null;
  ended_at: string | null;
  status: string;
  elo_change: number | null;
}

// ---------------------------------------------------------------------------
// PvE Challenge
// ---------------------------------------------------------------------------

export interface PvEProblemInfo {
  contest_id: number;
  index: string;
  name: string;
  rating: number | null;
  tags: string[];
  url: string;
}

export interface PvEStartResponse {
  session_id: string;
  problem: PvEProblemInfo;
  status: string;
}

export interface PvEDetailResponse {
  id: string;
  user_id: string;
  problem_id: string;
  problem_rating: number;
  problem_tags: string[];
  problem: PvEProblemInfo | null;
  status: string;
  error_count: number;
  time_spent: number | null;
  hints_used: number;
  elo_change: number | null;
  pp_change: number | null;
  s_value: number | null;
  created_at: string | null;
  completed_at: string | null;
}

export interface AchievementEvent {
  type: string;
  title: string;
  description: string;
  icon: string;
}

export interface PvESubmitResultResponse {
  session_id: string;
  solved: boolean;
  status: string;
  elo_change: number | null;
  pp_change: number | null;
  s_value: number | null;
  tokens_earned: number;
  overkill_multiplier: number;
  achievements: AchievementEvent[];
}

export interface PvEQuitResponse {
  session_id: string;
  status: string;
  elo_change: number | null;
  penalty: number | null;
}

export interface PvEHistoryItem {
  id: string;
  problem_id: string;
  problem_rating: number;
  problem_tags: string[];
  status: string;
  error_count: number;
  time_spent: number | null;
  hints_used: number;
  elo_change: number | null;
  pp_change: number | null;
  s_value: number | null;
  created_at: string | null;
  completed_at: string | null;
}

export interface PvEHistoryResponse {
  items: PvEHistoryItem[];
  total: number;
  page: number;
  page_size: number;
}

// ---------------------------------------------------------------------------
// Economy
// ---------------------------------------------------------------------------

export interface TokenBalance {
  tokens: number;
  daily_tokens_earned: number;
  daily_cap: number;
  daily_remaining: number;
}

export interface TransactionItem {
  id: string;
  amount: number;
  type: string;
  reference_type: string | null;
  reference_id: string | null;
  balance_after: number;
  created_at: string | null;
}

export interface TransactionList {
  items: TransactionItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface DailyStatus {
  date: string;
  daily_tokens_earned: number;
  daily_cap: number;
  daily_remaining: number;
  breakdown: Record<string, number>;
}

// ---------------------------------------------------------------------------
// Dashboard / Visualization
// ---------------------------------------------------------------------------

export interface EloHistoryPoint {
  date: string;
  elo: number;
  change: number;
}

export interface RadarDataPoint {
  topic: string;
  value: number;
  fullMark: number;
}

// ---------------------------------------------------------------------------
// M-Elo (per-tag Elo)
// ---------------------------------------------------------------------------

export interface UserTagEloInfo {
  tag: string;
  elo: number;
  total_submissions: number;
  first_ac_at: string | null;
  shield_active: boolean;
}

export interface MEloListResponse {
  melos: UserTagEloInfo[];
  global_elo: number;
}

export interface PPContributionItem {
  problem_id: string;
  problem_name: string;
  rating: number;
  pp: number;
}

export interface DifficultyDistribution {
  difficulty: string;
  count: number;
  color: string;
}

export interface DashboardStats {
  total_solved: number;
  difficulty_distribution: DifficultyDistribution[];
  challenge_win_rate: number;
  challenge_total: number;
  challenge_wins: number;
  total_tokens_earned: number;
  total_tokens_spent: number;
}

// ---------------------------------------------------------------------------
// Admin
// ---------------------------------------------------------------------------

export interface AdminSystemStats {
  users: { total: number; active: number };
  challenges: { total: number; active: number };
  training: { total_sessions: number; active_sessions: number };
  contests: { total: number; active: number };
}

export interface AdminUserItem {
  id: string;
  username: string;
  email: string;
  elo: number;
  pp: number;
  tokens: number;
  is_active: boolean;
  is_admin: boolean;
  created_at: string | null;
  last_login_at: string | null;
}

export interface AdminUserList {
  items: AdminUserItem[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

// ---------------------------------------------------------------------------
// Contest Leaderboard (AI bots + human)
// ---------------------------------------------------------------------------

export interface LeaderboardEntry {
  rank: number;
  name: string;
  elo: number;
  solved: number;
  is_bot: boolean;
}

export interface LeaderboardResponse {
  leaderboard: LeaderboardEntry[];
  time_elapsed: number;
  time_total: number;
}

export interface ContestEndedMessage {
  type: "contest_ended";
  leaderboard: LeaderboardResponse;
}

// ---------------------------------------------------------------------------
// Free Play
// ---------------------------------------------------------------------------

export interface FreePlayProblemInfo {
  contest_id: number;
  index: string;
  name: string;
  rating: number | null;
  tags: string[];
  url: string;
  difficulty_label: string;
}

export interface FreePlaySearchResponse {
  problems: FreePlayProblemInfo[];
  found: boolean;
  message: string;
}

export interface FreePlayRecommendResponse {
  problems: FreePlayProblemInfo[];
  found: boolean;
  message: string;
  recommended_tag: string | null;
}

export interface FreePlayStartResponse {
  session_id: string;
  problem: FreePlayProblemInfo;
  status: string;
  started_at: string | null;
}

export interface FreePlaySubmitResponse {
  session_id: string;
  solved: boolean;
  status: string;
  elo_change: number | null;
  pp_change: number | null;
  s_value: number | null;
  tokens_earned: number;
  overkill_multiplier: number;
  achievements: AchievementEvent[];
}

export interface FreePlayQuitResponse {
  session_id: string;
  status: string;
  elo_change: number | null;
  new_elo: number | null;
  penalty: number | null;
}

// ---------------------------------------------------------------------------
// Medal System
// ---------------------------------------------------------------------------

export interface MedalInfo {
  level: string;
  type?: string;
}

export interface OverallMedalResponse {
  elo: number;
  medal: MedalInfo;
}

export interface SkillMedalItem {
  tag: string;
  level: string;
  type?: string;
  melo: number;
}

export interface SkillMedalsResponse {
  skills: SkillMedalItem[];
}

export interface MedalStatsResponse {
  stats: Record<string, Record<string, number>>;
  total_medals: number;
}

export interface UserMedalPublicResponse {
  user_id: string;
  username: string;
  overall_medal: MedalInfo;
  medal_stats: Record<string, Record<string, number>>;
  total_medals: number;
}

export interface UserSettingsData {
  display_mode: "medal" | "cf_tier";
}

// ---------------------------------------------------------------------------
// Check-in
// ---------------------------------------------------------------------------

export interface CheckInStatusData {
  checked_in_today: boolean;
  streak_days: number;
  last_checkin_date: string | null;
  makeup_used_this_week: number;
  makeup_limit: number;
  next_reward: number;
  can_makeup: boolean;
  checked_dates_this_week: string[];
}

export interface CheckInResponseData {
  checkin_date: string;
  streak_days: number;
  tokens_awarded: number;
  is_makeup: boolean;
  tokens_balance: number;
}

// ---------------------------------------------------------------------------
// PP Rank
// ---------------------------------------------------------------------------

export interface PPRankData {
  rank: number | null;
  total_users: number;
  top_percent: number | null;
  calibrated: boolean;
}

// ---------------------------------------------------------------------------
// Global Ranking
// ---------------------------------------------------------------------------

export interface GlobalRankingItem {
  rank: number;
  name: string;
  pp: number;
  country: string | null;
  verified: boolean;
  cf_rating?: number;
  estimated_percentile?: number | null;
}

export interface ArenaRankingItem {
  rank: number;
  name: string;
  pp: number;
  elo: number;
  country: string | null;
  verified: boolean;
}

export interface RankingPageData<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  calibrated?: boolean;
}
