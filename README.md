# CleanseMeMaybe

> Hey, I just decoded config, and this is crazy, but here's my `condition.config`, execute me maybe?

Craft CMS 5.10.1 authenticated RCE via `condition.config` JSON decode-after-cleanse bypass.

**Still unpatched** in 5.10.4.1 (2026-05-28).

## What

Craft calls `Component::cleanseConfig()` to strip dangerous Yii keys like `as ...` and `on ...`. Then `Conditions::createCondition()` decodes the JSON string inside `condition.config` and merges it back in **after** the cleanse. The decoded payload reintroduces those keys, reaches `Craft::createObject()`, and Yii interprets them as behavior/event config. RCE.

## Requirements

- Authenticated CP session (non-admin `accessCp` is enough)
- Valid CSRF token from `/admin/dashboard` body

## Files

```
├── README.md           # You are here
├── STORYTIME.md        # How this was found
├── poc.py              # Automated PoC
└── burp/
    ├── trigger.txt     # Raw trigger request
    └── verify.txt      # Raw verification request
```

## Quick PoC

```bash
python3 poc.py --url https://craft.example.com --cookie "CRAFT_CSRF_TOKEN=...; craft_session=..." --cmd id
```

## Root Cause

```
POST /admin/actions/element-search/search
  → cleanseConfig()          ← strips "as"/"on" from direct array keys
  → createCondition()
    → Json::decode(config)   ← decoded AFTER cleanse
    → merge back             ← "as"/"on" keys reintroduced
    → Craft::createObject()  ← Yii behavior/event injection → shell_exec()
```

## Vulnerable Code

Commit: [`90ce464e804d95c996c8b1f382adefecc4c6353b`](https://github.com/craftcms/cms/tree/90ce464e804d95c996c8b1f382adefecc4c6353b)

### 1. The sanitizer (`src/helpers/Component.php` line 92)

This walks the config array and removes keys starting with `as ` or `on `. But it only checks array keys. JSON string values are ignored.

```php
public static function cleanseConfig(array $config): array
{
    foreach ($config as $key => $value) {
        if (is_string($key) && (str_starts_with($key, 'on ') || str_starts_with($key, 'as '))) {
            unset($config[$key]);
            continue;
        }
        if (is_array($value)) {
            $config[$key] = static::cleanseConfig($value);
        }
    }
    return $config;
}
```

### 2. The entry point (`src/controllers/ElementSearchController.php` line 69)

Cleanse runs here. Direct `as`/`on` keys in the outer array are stripped. Then the sanitized config is passed to `createCondition()`.

```php
$condition = Craft::$app->getConditions()->createCondition(Component::cleanseConfig($conditionConfig));
```

### 3. The vuln (`src/services/Conditions.php` line 54)

Here is the bug. `condition.config` is a JSON string. The cleanse already ran and didn't touch it because it's a string, not an array key. Now it gets decoded and merged back in, reintroducing every `as`/`on` key the sanitize removed.

```php
// The base config will be JSON-encoded within a `config` key if this came from a condition builder
if (isset($config['config']) && Json::isJsonObject($config['config'])) {
    $config = array_merge(
        Json::decode(ArrayHelper::remove($config, 'config')),  // ← decoded AFTER cleanse
        $config
    );
}

// ...
return Craft::createObject([   // ← attacker-controlled config reaches Yii object creation
    'class' => $class,
    'attributes' => $config,
    'conditionRules' => $rules,
]);
```

## Unpatched Evidence

GitHub API compare `5.10.1...5.10.4.1`: zero changes to any file in the vulnerable path:

- `src/helpers/Component.php`
- `src/services/Conditions.php`
- `src/controllers/ElementSearchController.php`
- `src/elements/conditions/ElementCondition.php`

## Disclaimer

Authorized security research only. Test only systems you own or have permission to test.

Also, dear triager: I know you're busy, but have some basic courtesy. A one-line reply isn't that hard.
