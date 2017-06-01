import unittest

from org.openbaton.cli.agents.agents import OpenBatonAgentFactory

from eu.softfire.nfv.utils import get_config


class MyTestCase(unittest.TestCase):
    def test_openbaton(self):
        config = get_config()
        agent = OpenBatonAgentFactory(nfvo_ip=config.get("nfvo", "ip"),
                                      nfvo_port=config.get("nfvo", "port"),
                                      https=config.getboolean("nfvo", "https"),
                                      version=1,
                                      username=config.get("nfvo", "username"),
                                      password=config.get("nfvo", "password"),
                                      project_id=None)
        for pj in agent.get_project_agent().find():
            print(pj)

if __name__ == '__main__':
    unittest.main()
