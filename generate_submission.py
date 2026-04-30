import sys, json, os
sys.path.insert(0, 'D:\\Downloads\\vera-bot')

from context_store import ContextStore
from category import get_category_rules, get_trigger_strategy
from compose import build_fallback, resolve_digest_item, _compose_action
from prompts import build_compose_prompt, COMPOSER_SYSTEM
from llm import call_llm_json

store = ContextStore()
EXPANDED = 'D:\\Downloads\\magicpin-ai-challenge\\expanded'

ID_FIELDS = {'category':'slug','merchant':'merchant_id','customer':'customer_id','trigger':'id'}
for scope, subdir in [('category','categories'),('merchant','merchants'),('customer','customers'),('trigger','triggers')]:
    dpath = os.path.join(EXPANDED, subdir)
    for fname in sorted(os.listdir(dpath)):
        with open(os.path.join(dpath, fname), encoding='utf-8') as f:
            obj = json.load(f)
        cid = obj.get(ID_FIELDS[scope])
        if cid:
            store.upsert(scope, cid, 1, obj)

print(f"Contexts: {store.counts()}")

with open(os.path.join(EXPANDED, 'test_pairs.json'), encoding='utf-8') as f:
    pairs = json.load(f)['pairs']

results = []
for pair in pairs:
    test_id = pair['test_id']
    trigger = store.get('trigger', pair['trigger_id'])
    merchant, category = store.get_merchant_with_category(pair['merchant_id'])
    customer = store.get('customer', pair.get('customer_id')) if pair.get('customer_id') else None

    if not trigger or not merchant or not category:
        print(f"SKIP {test_id}")
        continue

    kind = trigger.get('kind', '')
    cat_rules = get_category_rules(category.get('slug', 'restaurants'))
    strategy = get_trigger_strategy(kind)
    send_as = strategy.get('send_as', cat_rules.get('send_as_default', 'vera'))
    if customer:
        send_as = 'merchant_on_behalf'

    digest_item = None
    if kind in ('research_digest', 'regulation_change', 'cde_opportunity'):
        digest_item = resolve_digest_item(trigger, category)

    try:
        prompt = build_compose_prompt(category, merchant, trigger, customer, strategy, cat_rules, digest_item)
        result = call_llm_json(COMPOSER_SYSTEM, prompt, max_tokens=600)
        body = result.get('body', '')
        cta = result.get('cta', 'open_ended')
        rationale = result.get('rationale', '')
        print(f"OK  {test_id} ({kind})")
    except Exception as e:
        fb = build_fallback(merchant, trigger, category, customer)
        body, cta, rationale = fb['body'], fb['cta'], fb['rationale'] + f' [fallback: {str(e)[:60]}]'
        print(f"FB  {test_id} ({kind})")

    from datetime import datetime, timezone
    date_part = datetime.now(timezone.utc).strftime('%Y%m%d')
    results.append({
        'test_id': test_id,
        'body': body,
        'cta': cta,
        'send_as': send_as,
        'suppression_key': trigger.get('suppression_key', f'{pair["merchant_id"]}:{kind}:{date_part}'),
        'rationale': rationale,
        'conversation_id': f'conv_{pair.get("customer_id") or pair["merchant_id"]}_{kind}_{date_part}',
        'merchant_id': pair['merchant_id'],
        'customer_id': pair.get('customer_id'),
        'trigger_id': pair['trigger_id'],
    })

out = 'D:\\Downloads\\vera-bot\\submission.jsonl'
with open(out, 'w', encoding='utf-8') as f:
    for r in results:
        f.write(json.dumps(r, ensure_ascii=False) + '\n')
print(f"\nWrote {len(results)} lines to {out}")
