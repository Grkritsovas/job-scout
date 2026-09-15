# Personalizing Your Job Search

Think of your profile as a short brief for someone helping you find work:
what you can do, what you want to do next, and what matters to you.

You do not need to write code or learn special AI instructions. Use the examples
below as starting points and change them to sound like you.

## Open Your Profile

In the profile editor, select your profile or click **New**. Check your email
address and make sure **enabled** is on if you want to receive jobs.
If you need to open the editor first, see [starting the profile editor](CONFIGURATION.md#local-admin-ui).

## Choose The Jobs You Want

Under **Candidate**, use **Add Role** for each kind of work you would apply for.
Remove example roles you do not want, and keep at least one.

Each role has three boxes:

- **id:** a short label, such as `digital_marketing`, `customer_service`, `hr`,
  or `software_engineer`.
- **name:** the job name you would normally use, such as "Digital Marketing".
- **match_text:** a few sentences about the work you want and the experience
  or skills you bring to it.

Here are some examples for **match_text**. Use only details that are true for you.

**Digital marketing**

> I want to help with social media, email campaigns, and content planning. I have
> written social posts, used Canva, and tracked campaign results in Excel.
> I would like to work in a team where I can learn more about digital marketing.

**Customer service**

> I am looking for customer support work by email, chat, or phone. I have helped
> customers with orders and complaints, explained next steps clearly, and kept
> records up to date. I am comfortable working in Greek and English.

**HR**

> I am interested in HR assistant, recruitment coordinator, and people
> administration roles. I have organised appointments, maintained records,
> and helped new colleagues settle in. I enjoy communication and organisation.

**Software development**

> I am looking for junior software development work. I have built small Python
> applications, worked with SQL databases, and used Git. I would like to work
> alongside experienced developers and build on those skills.

You can choose more than one area. There is no need to describe every possible
job title: focus on the work you would enjoy and could realistically do.

## Tell Us About Yourself

In **candidate.summary**, write a short introduction. Include your experience,
a couple of things you have done, and any languages you can work in.
Study, volunteering, and personal projects count too; just say which they are.

For example:

> I have worked in customer service for two years and would like to move into
> digital marketing. Alongside my job, I helped a local business plan Instagram
> posts and prepare a monthly email newsletter. I use Canva and Excel and work
> comfortably in Greek and English. I am looking for an assistant-level role
> where I can learn from a team.

For each role's **match_text**, include the skills from your introduction that
are relevant to that role. It is fine to reuse a sentence.

In **candidate.education_status**, briefly say whether you are studying or have
finished, for example "Graduated in June 2026".

If permission to work is relevant, describe your situation in
**eligibility.work_authorization_summary**, for example "I can work in Greece
without employer sponsorship." Leave the other eligibility settings alone
unless the person running the app has helped you choose them.

## Choose Where You Want To Work

In **job_preferences.location**, choose **Greece** or **UK**.

For remote-only work, also say that in the instructions below. Choosing Greece
on its own includes office-based jobs in Greece.

In **delivery.language**, enter **Greek** if you want the AI's reasons for
recommending jobs written in Greek. This is separate from the languages you can
use at work, which belong in your introduction.

## Say What Matters To You

The **LLM Review** section lets you give the AI reviewer a few extra instructions.
Write normally, as if you were explaining your preferences to another person.
These instructions are used when AI review is enabled for the app.

**First box: extra_screening_guidance**

Use this for things a job needs to meet. Enter one instruction per line.
For someone looking for remote work from Greece:

```text
I need fully remote work from Greece, with no regular office attendance.
I can work in Greek and English. Skip jobs that require another language.
I want a support or assistant role, not a role managing a team.
```

**Second box: extra_final_ranking_guidance**

Use this for deciding which suitable jobs you would be most interested in.
Repeat anything essential, such as remote-only work, here too.

```text
Keep the recommendations limited to fully remote work from Greece.
Prefer jobs with training and a supportive team.
For marketing jobs, I am most interested in content and email campaigns.
```

A few other examples you could use:

- "I prefer email and chat support over phone-based work."
- "I am interested in HR administration and recruitment coordination."
- "I cannot work overnight shifts."
- "Avoid jobs mainly focused on sales calls or commission."
- "I am happy to learn a new tool if training is provided."

Pick only the instructions that matter to you. "Prefer" leaves room for
alternatives; "I need" or "avoid" makes a stronger request. A short, clear list
is enough. You can leave either box empty if you have nothing to add.

## Save And Adjust

Click **Save** when you are done. Saved changes will be used by future runs;
you do not need to push anything to GitHub or edit the example JSON files.

Set the advertised experience limit in **max_explicit_years** to suit the jobs
you want to consider. For example, use `2` if you want to consider jobs asking
for up to two years. You can leave the matching threshold and title-boost
settings at their defaults to start with.

After a few emails, adjust one or two things based on what you see. Too many
sales roles? Say you want customer support without sales targets. The wrong
kind of marketing? Describe the tasks you actually want to do.

Recommendations are a starting point, so check the job's location and language
requirements before applying. If there are very few results, ask the person
running the app to check its company lists and filters too.

For setup, advanced settings, and troubleshooting, use the
[configuration reference](CONFIGURATION.md).

## Prefer To Talk It Through?

Use the [AI profile helper prompt](PROFILE_INTERVIEW_PROMPT.md) in your preferred
AI chat. It will ask a few questions, help you put your experience and preferences
into words, and prepare a profile for you to review.

You can give it everything at once, answer one question at a time, or say
"draft it now". You can also skip private details and add your email later.
When you are happy with the result, enter it in the profile editor or give it
to the person running JOB-SCOUT.
