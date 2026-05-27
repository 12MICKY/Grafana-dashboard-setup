.PHONY: validate smoke-test deploy-k3s

validate:
	scripts/validate.sh

smoke-test:
	scripts/smoke-test.sh

deploy-k3s:
	scripts/deploy-k3s.sh
