$envFile = ".env"
if (Test-Path $envFile) {
  Get-Content $envFile | ForEach-Object {
    if ($_ -match '^\s*#' -or $_ -match '^\s*$') { return }
    $parts = $_ -split '=', 2
    if ($parts.Count -eq 2) {
      $key = $parts[0].Trim()
      $value = $parts[1].Trim().Trim('"')
      [Environment]::SetEnvironmentVariable($key, $value, 'Process')
    }
  }
}

if (-not $env:SUPABASE_URL -or -not $env:SUPABASE_SERVICE_ROLE_KEY) {
  throw "Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in backend .env"
}

$base = "$($env:SUPABASE_URL.TrimEnd('/'))/rest/v1"
$headers = @{
  Authorization = "Bearer $($env:SUPABASE_SERVICE_ROLE_KEY)"
  apiKey = "$($env:SUPABASE_SERVICE_ROLE_KEY)"
  "Content-Type" = "application/json"
  Prefer = "return=representation"
}

$studentId = "e41733dc-6b6b-46f9-ad1e-ee7ed6c76a9e"
$examId = 3

$assigned = Invoke-RestMethod -Uri "http://127.0.0.1:5000/api/students/$studentId/assigned-exams" -Method Get
$exam = $assigned.exams | Where-Object { [int]$_.id -eq $examId } | Select-Object -First 1
if (-not $exam) { throw "Assigned exam $examId not found for student $studentId" }

$topics = @()
if ($exam.topics -is [string]) {
  try { $topics = @($exam.topics | ConvertFrom-Json) } catch { $topics = @() }
} elseif ($exam.topics -is [System.Array]) {
  $topics = @($exam.topics)
}
if ($topics.Count -eq 0) {
  $topics = @(
    @{ id = 1; name = "Topic 1" },
    @{ id = 2; name = "Topic 2" },
    @{ id = 3; name = "Topic 3" }
  )
}

$totalItems = [int]$exam.total_items
if ($totalItems -le 0) { $totalItems = 100 }
$topicCount = [Math]::Max(1, $topics.Count)
$baseMax = [Math]::Floor($totalItems / $topicCount)
$remainder = $totalItems % $topicCount

$topicScores = @()
$computedScore = 0
for ($i = 0; $i -lt $topicCount; $i++) {
  $topic = $topics[$i]
  $max = [int]$baseMax
  if ($i -eq ($topicCount - 1)) { $max += [int]$remainder }
  if ($max -le 0) { $max = 1 }
  $score = [Math]::Max(0, $max - 2)
  $computedScore += $score
  $topicScores += @{
    topicId = $topic.id
    score = $score
    maxScore = $max
  }
}

$profileResp = Invoke-RestMethod -Uri "$base/profiles?select=first_name,last_name&user_id=eq.$studentId&limit=1" -Headers $headers -Method Get
$studentName = "Seed Student"
if ($profileResp.Count -gt 0) {
  $fullName = ("$($profileResp[0].first_name) $($profileResp[0].last_name)").Trim()
  if ($fullName) { $studentName = $fullName }
}

$existing = Invoke-RestMethod -Uri "$base/exam_results?select=exam_id,student_id&exam_id=eq.$examId&student_id=eq.$studentId" -Headers $headers -Method Get

$basePayload = @{
  exam_id = $examId
  student_id = $studentId
  student_name = $studentName
  score = $computedScore
  total_items = $totalItems
  passed = $true
  feedback = "Great progress across all topics. Keep reviewing weak items before the next exam."
  updated_at = (Get-Date).ToUniversalTime().ToString("o")
}

try {
  $payloadObj = $basePayload.Clone()
  $payloadObj["topic_scores"] = $topicScores
  $json = $payloadObj | ConvertTo-Json -Depth 8 -Compress
  if ($existing.Count -gt 0) {
    Invoke-RestMethod -Uri "$base/exam_results?exam_id=eq.$examId&student_id=eq.$studentId" -Headers $headers -Method Patch -Body $json | Out-Null
  } else {
    $payloadObj["created_at"] = (Get-Date).ToUniversalTime().ToString("o")
    $json = $payloadObj | ConvertTo-Json -Depth 8 -Compress
    Invoke-RestMethod -Uri "$base/exam_results" -Headers $headers -Method Post -Body $json | Out-Null
  }
} catch {
  $payloadObj = $basePayload.Clone()
  $payloadObj["topic_scores"] = ($topicScores | ConvertTo-Json -Depth 8 -Compress)
  if ($existing.Count -gt 0) {
    $json = $payloadObj | ConvertTo-Json -Depth 8 -Compress
    Invoke-RestMethod -Uri "$base/exam_results?exam_id=eq.$examId&student_id=eq.$studentId" -Headers $headers -Method Patch -Body $json | Out-Null
  } else {
    $payloadObj["created_at"] = (Get-Date).ToUniversalTime().ToString("o")
    $json = $payloadObj | ConvertTo-Json -Depth 8 -Compress
    Invoke-RestMethod -Uri "$base/exam_results" -Headers $headers -Method Post -Body $json | Out-Null
  }
}

$verify = Invoke-RestMethod -Uri "http://127.0.0.1:5000/api/students/$studentId/assigned-exams" -Method Get
$seeded = $verify.exams | Where-Object { [int]$_.id -eq $examId } | Select-Object -First 1

Write-Output "SEEDED_OK=True"
Write-Output ("EXAM_ID=" + $seeded.id)
Write-Output ("TITLE=" + $seeded.exam_title)
Write-Output ("SCORE=" + $seeded.score)
Write-Output ("TOTAL_ITEMS=" + $seeded.result_total_items)
Write-Output ("ATTEMPTED=" + $seeded.attempted)
Write-Output ("HAS_TOPIC_SCORES=" + ($null -ne $seeded.PSObject.Properties['topic_scores']))
Write-Output ("HAS_FEEDBACK=" + (-not [string]::IsNullOrWhiteSpace([string]$seeded.feedback)))
