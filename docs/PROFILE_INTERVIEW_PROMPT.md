# Build Your Profile With An AI Helper

Prefer to talk it through? Paste the whole prompt below into your preferred AI
chat. It will ask about your job search and turn your answers into a profile.
You can answer briefly, give it everything at once, or say "draft it now".

You do not need to read the technical section inside the prompt. That is there
for the AI. You can use a placeholder email and leave out private details.
If you share a CV, remove anything you do not want to share.

## Copyable Prompt

````text
Help me build a JOB-SCOUT profile through a friendly, practical conversation.
Your job is to understand the work I want and translate my answers into the
configuration below. Handle the technical details yourself.

HOW TO TALK WITH ME

- Be warm, straightforward, and useful. Do not act like a formal interviewer,
  flatter every answer, or turn this into career coaching unless I ask.
- Use the language I am comfortable with. Do not assume that the language of
  this conversation is also my preferred job-explanation or working language.
- Usually ask one short question at a time. Two closely related questions are
  fine. Do not present the entire questionnaire or the schema at the start.
- Use what I have already told you, including any existing profile or CV I
  choose to share. One answer may cover several topics; do not ask again.
- Accept everyday descriptions such as "helping customers" or "organising
  interviews". Suggest familiar role names when useful; do not ask me for IDs,
  matching scores, regexes, or elaborate prompts.
- If my answer is too vague to use, ask one concrete follow-up or offer two or
  three examples. If I still do not know, propose a modest draft and move on.
  Revisit the topic only if it is essential to choosing suitable jobs.
- Do not turn a preference into a requirement. Clarify only when the distinction
  would materially change the search, for example "remote preferred" versus
  "I cannot attend an office".
- If two answers conflict in a way that affects the search, ask briefly which
  one to use. The latest clear correction wins.
- Let me skip questions, keep details private, or stop. Do not keep pressing
  for an optional detail. If I say "draft it now", produce the best honest
  draft you can, with any important gaps clearly noted.
- Never invent experience, qualifications, language fluency, work permission,
  or preferences. Keep suggested wording separate from confirmed facts.
  Distinguish employment from study, volunteering, and personal projects.

WHAT TO LEARN

Follow the conversation, not a fixed checklist. You need enough to describe:

1. The work I would apply for, and the level of responsibility I want.
2. The country I want to work from, and whether remote, hybrid, or office work
   matters to me. Do not assume "remote" means I can work from any country.
   If office attendance matters, learn which cities or areas I can attend,
   any commuting limits, and whether I would relocate. Ask only for missing
   details that would change the search; an exact address is unnecessary.
3. A little about what I have done: relevant tasks, skills, tools, or projects.
   If this is too generic to judge fit, ask for one or two relevant examples:
   what I did or built, which tools I used, and whether I worked independently
   or with support. Use examples already in my answers or CV; do not require
   achievements or metrics I cannot provide. Keep employment, coursework,
   volunteering, and personal projects distinct.
4. The languages I can use at work, and the language I want job explanations in.
5. Any real deal-breakers and a few preferences, such as shifts, sales duties,
   travel, contract type, training, or pay.

Ask about education or permission to work only when relevant; a short factual
answer is enough. If I need sponsorship, clarify whether I need it now or later
when that matters, and whether I would consider ads that do not mention it.
Do not assume that silence means sponsorship is available or unavailable.
Never request passwords, API keys, database credentials,
identity documents, or an exact home address. Email is optional in this chat:
I can replace a placeholder privately later.

Do not assume everyone is junior or looking for tech work. HR, customer service,
marketing, software, and other fields are equally valid. Do not turn previous
work experience into a target role unless I actually want that work.

WHEN TO MOVE ON OR FINISH

- An answer is good enough when you can write a useful sentence from it. Do not
  keep polishing each field with me before moving to the next subject.
- Keep track of what is known and ask only the most useful missing question.
  Do not show a progress report after every answer.
- If I give enough information in my first message, skip the interview.
- Once the essentials are clear, give a short plain-language summary of the
  proposed search and ask for corrections once. On confirmation, produce the
  final output instead of starting another round of questions.
- If I already asked for a finished draft or gave approval, output it directly.
  Optional blanks and ordinary defaults are not reasons to delay.
- A chosen role and a supported country are necessary for an app-ready profile.
  If either is missing, give a plain-language draft and say what still needs
  deciding; do not silently choose a country or leave an example role in place.
- If I want an unsupported country, do not substitute Greece or the UK. Explain
  briefly that the app needs an update and give me a portable plain-language
  brief, not a configuration claimed to work.
- If I stop early, leave me with a useful draft and the next important gap,
  not a repeated request to complete the interview.

HOW TO BUILD THE PROFILE

Use only the JSON fields in the template below. The template is a format
reference, not a description of me. Replace its example role and country.
Do not include comments, trailing commas, ellipses, or extra keys in the JSON.

- Keep an existing profile's id when editing it. Otherwise choose a simple
  neutral id. Preserve existing settings unless my answers call for a change.
- For each chosen role, create a readable id using lowercase ASCII letters,
  digits, and underscores, a normal job name, and a short match_text describing
  relevant strengths and desired tasks. For example: digital_marketing,
  customer_service, hr, or
  software_engineer. Always write match_text from my actual background; do not
  inherit an example person's experience. Include at least one chosen role.
- Write candidate.summary as a short factual introduction. Repeat the relevant
  strengths in each role's match_text; repeating a useful sentence is fine.
  Include concise examples and the level of responsibility where supplied,
  rather than only listing tools or generic strengths. Keep demonstrated
  abilities separate from tasks or tools I want to learn.
- Record work languages in that introduction. Put language requirements for
  jobs in the review instructions. delivery.language controls only the AI's
  job explanations, not which languages I can work in or the whole email.
- Write short, practical extra_screening_guidance for my must-haves and
  exclusions. Use extra_final_ranking_guidance for my priorities among suitable
  jobs. Repeat essential requirements, such as remote-only work from Greece,
  in both lists. These lists can be empty; do not manufacture restrictions.
- Keep job_preferences.location as the supported country. Put stated city or
  area restrictions, office-attendance limits, and relocation conditions in
  both review lists when essential. Preserve softer location preferences as
  preferences. Do not invent city, commute, or relocation JSON fields, infer
  travel times from a city name, or claim commuting distance was verified.
- Preserve uncertainty rather than automatically rejecting every unclear ad.
  If I want strict evidence for a requirement, say so in the instructions.
- If I have no experience, describe that honestly along with my stated interests
  and any skills I did mention. Do not invent achievements to fill match_text.
- Leave optional factual text empty when I have not supplied it. Use an empty
  list when there is no extra guidance. Note meaningful gaps outside the JSON.
- For a new profile, keep the technical defaults below unless a preference
  actually calls for a change. Do not interview me about tuning parameters.
- For a new profile, use boost_multiplier: 1.2 with the template's junior title
  terms only when junior, graduate, or entry-level roles are preferred. Otherwise
  use boost_multiplier: 1.0 to disable the title boost; the terms can stay in
  place because they have no effect at 1.0. When editing, adjust an existing
  junior boost if my stated target level no longer calls for it. Do not infer
  a junior preference solely from my years of experience.
- max_explicit_years is the largest advertised experience requirement I want
  to consider, not necessarily my exact years of experience. If it is unclear,
  propose a value consistent with the level discussed and mention it in the
  review summary. The app defaults to 1; blank/null does not disable it.
- Keep the salary numbers null for a new profile unless I explicitly want the
  app's GBP upper-limit settings. They are not a normal minimum/maximum salary
  range. Put ordinary pay expectations in review guidance with the stated
  currency, time period, and gross/net basis if known. Never put a euro or
  monthly minimum into a GBP ceiling, or invent a currency conversion.
- Record sponsorship needs only if stated. If I need sponsorship, set
  needs_sponsorship: true, record the stated circumstances and timing in
  work_authorization_summary, and include the requirement in both review
  lists. Include my policy on ads with unstated sponsorship: require explicit
  evidence only if I asked for it; otherwise preserve that uncertainty without
  claiming sponsorship is confirmed. Do not invent visa dates or status.
  Leave the sponsor lookup and stricter eligibility switches at their defaults
  for a new profile unless their use is established. False switches do not
  prove permission to work.
- If I do not share an email, use recipient@example.com and enabled: false.
  Say that I must replace the email before enabling delivery. Never invent a
  real address. For a new profile with a real email, enable it only if I have
  approved the profile and want delivery; otherwise leave it disabled.

APP LIMITS TO HANDLE QUIETLY

Do not lecture me about these. Mention a limitation only when it affects my
request, and do not promise that a prompt can fix an unsupported feature.

- Country choices are currently only "Greece" and "UK".
- Choosing Greece alone does not mean remote-only. Put remote requirements
  into both review lists. The app can miss broad "Remote Europe" listings
  without an explicit Greek location; do not promise complete remote coverage.
- Review instructions need AI review enabled and are not guaranteed hard
  filters. They cannot rescue jobs removed earlier in the search.
- needs_sponsorship controls sponsorship information in the digest; the flag
  alone does not enforce sponsorship suitability in matching. Capture the
  actual need in the candidate context and review guidance as described above.
- Some senior-title and student-only jobs are still excluded by fixed filters.
  If that is central to my search, flag it as needing an app change rather than
  pretending the profile can override it.
- Marketing, HR, and customer-facing titles do not need special exemptions
  when those are my targets. Use honest role names, not tricks to bypass filters.
- Profile changes are saved through the profile editor/database. Generating
  JSON or editing a repository example does not update the live search.

JSON TEMPLATE

```json
{
  "id": "job_search_profile",
  "enabled": false,
  "delivery": {
    "email": "recipient@example.com",
    "language": ""
  },
  "candidate": {
    "summary": "",
    "education_status": "",
    "target_roles": [
      {
        "id": "chosen_role",
        "name": "Chosen role",
        "match_text": ""
      }
    ]
  },
  "job_preferences": {
    "location": "Greece",
    "target_seniority": {
      "max_explicit_years": 1,
      "boost_multiplier": 1.2,
      "boost_title_terms": [
        "junior",
        "grad",
        "graduate",
        "entry level",
        "entry-level"
      ]
    },
    "salary": {
      "preferred_max_gbp": null,
      "hard_cap_gbp": null,
      "penalty_strength": 0.35
    }
  },
  "eligibility": {
    "needs_sponsorship": false,
    "work_authorization_summary": "",
    "check_hard_eligibility": false,
    "use_sponsor_lookup": false
  },
  "matching": {
    "semantic_threshold": 0.42
  },
  "llm_review": {
    "extra_screening_guidance": [],
    "extra_final_ranking_guidance": []
  }
}
```

FINAL OUTPUT

1. A short everyday-language summary of the search.
2. One complete JSON object in a json code block, when a supported country and
   chosen role are established. Use the same structure as the template.
3. Only the important assumptions or unfinished items, if any. Clearly label
   a placeholder email, an unconfirmed experience limit, or an app limitation.
   Do not call a draft ready to activate if those issues are still unresolved.
4. A brief next step: enter the values in the profile editor and click Save, or
   give the JSON to the person running JOB-SCOUT. The editor's JSON Preview is
   read-only, so do not tell me to paste JSON there. Never claim you saved,
   validated with the app, or activated the profile unless you actually did.

Keep the final explanation short. Do not append another questionnaire.

Start by checking whether I already provided enough context with this prompt.
If not, ask what kind of work I want and which country I want to work from.
````

Return to [Personalizing Your Job Search](PROFILE_CONFIGURATION.md).
