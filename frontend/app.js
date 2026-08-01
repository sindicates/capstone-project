document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('triage-form');
    const replyForm = document.getElementById('reply-form');
    const inputSection = document.getElementById('input-section');
    const processingSection = document.getElementById('processing-section');
    const resultSection = document.getElementById('result-section');
    const resultContent = document.getElementById('result-content');
    const resultHeading = document.getElementById('result-heading');
    const replyInput = document.getElementById('reply');
    const resetBtn = document.getElementById('reset-btn');

    let userId = null;
    let sessionId = null;

    marked.setOptions({ gfm: true, breaks: true });

    function switchSection(toShow) {
        // First fade out everything
        [inputSection, processingSection, resultSection].forEach(sec => {
            sec.classList.remove('active');
        });

        // After fade out transition (500ms), hide them and show the new one
        setTimeout(() => {
            [inputSection, processingSection, resultSection].forEach(sec => {
                if (sec !== toShow) sec.style.display = 'none';
            });

            toShow.style.display = 'flex';

            // Allow display block to render before triggering opacity transition
            requestAnimationFrame(() => {
                toShow.classList.add('active');
            });
        }, 500);
    }

    function isFinalIntake(text) {
        if (!text) return false;
        return (
            text.includes('# Legal Aid Intake Summary') ||
            text.includes('THIS DOCUMENT IS NOT LEGAL ADVICE') ||
            text.includes('## Situation Overview')
        );
    }

    function isClarification(text) {
        if (!text || isFinalIntake(text)) return false;
        const lower = text.toLowerCase();
        return (
            text.includes('?') ||
            lower.includes('i need to know') ||
            lower.includes('could you') ||
            lower.includes('before i get started')
        );
    }

    function prepareMarkdown(text) {
        if (!text) return '';
        let md = text.trim().replace(/\\n/g, '\n');

        const isIntake = (chunk) =>
            /# Legal Aid Intake Summary|THIS DOCUMENT IS NOT LEGAL ADVICE|## Situation Overview/.test(
                chunk
            );

        // Prefer a fenced block that contains the intake document (even if
        // handoff prose appears before/after the fence).
        const fences = [...md.matchAll(/```(?:markdown|md)?\r?\n([\s\S]*?)```/gi)];
        const intakeFence = fences.find((m) => isIntake(m[1]));
        if (intakeFence) {
            return intakeFence[1].trim();
        }

        // Whole-string fence fallback
        const whole = md.match(/^```(?:\w*)?\r?\n([\s\S]*?)\r?\n```$/);
        if (whole) {
            return whole[1].trim();
        }

        // If the model wrapped only the start/end with backticks without a
        // clean close, strip a leading fence line when content looks like intake.
        if (isIntake(md)) {
            md = md.replace(/^```(?:markdown|md)?\s*\r?\n/, '').replace(/\r?\n```\s*$/, '');
        }

        return md.trim();
    }

    function showResult(text) {
        const md = prepareMarkdown(text);
        const clarification = isClarification(md);
        resultContent.innerHTML = marked.parse(md);
        resultHeading.textContent = clarification
            ? 'Needs more info'
            : 'Intake Summary';
        replyForm.style.display = clarification ? 'flex' : 'none';
        replyInput.value = '';
        switchSection(resultSection);
    }

    async function runTriage(description, continueSession) {
        switchSection(processingSection);

        const body = { description };
        if (continueSession && userId && sessionId) {
            body.user_id = userId;
            body.session_id = sessionId;
        }

        try {
            const response = await fetch('/api/triage', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });

            if (!response.ok) {
                throw new Error('Server error during processing');
            }

            const data = await response.json();
            userId = data.user_id || null;
            sessionId = data.session_id || null;
            showResult(data.result);
        } catch (error) {
            console.error('Error:', error);
            resultHeading.textContent = 'Intake Summary';
            resultContent.textContent =
                'An error occurred while analyzing your case. Please try again.';
            replyForm.style.display = 'none';
            replyInput.value = '';
            switchSection(resultSection);
        }
    }

    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        const description = document.getElementById('situation').value.trim();
        if (!description) return;

        userId = null;
        sessionId = null;
        await runTriage(description, false);
    });

    replyForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        const reply = replyInput.value.trim();
        if (!reply) return;

        await runTriage(reply, true);
    });

    resetBtn.addEventListener('click', () => {
        userId = null;
        sessionId = null;
        document.getElementById('situation').value = '';
        replyInput.value = '';
        switchSection(inputSection);
    });
});
