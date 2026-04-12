# Project Description Validation Demo

## 1. Reject empty description (should return 422)
```
HTTP 422
{
  "detail": [
    {
      "type": "value_error",
      "loc": [
        "body",
        "description"
      ],
      "msg": "Value error, description must not be empty",
      "input": "",
      "ctx": {
        "error": {}
      }
    }
  ]
}
```

## 2. Accept valid description (should return 201)
```
HTTP 201
{
  "id": "46ef04e4-f53f-44d6-8d60-7690ee120b40",
  "name": "test-project-valid",
  "description": "A real project"
}
```

## 3. Omit description (should use default, return 201)
```
HTTP 201
{
  "id": "4e4dc23a-8864-49c4-b99d-49831ddb8f5f",
  "name": "test-project-default",
  "description": ""
}
```

