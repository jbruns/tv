import os

if os.environ.get("COREELEC_RECONCILER_TEST_COMPOSITION") == "1":
    from fixture_composition import application_factory

    from coreelec_reconciler.cli import main

    main.application_factory = application_factory
