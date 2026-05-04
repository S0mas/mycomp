"""Tests for aicompany/seeds.py"""
from aicompany.seeds import default_skills, default_teams
from aicompany.models import Person, Skill, Team


class TestDefaultSkills:
    def test_returns_non_empty_list(self):
        skills = default_skills()
        assert len(skills) > 0

    def test_all_are_skill_instances(self):
        for s in default_skills():
            assert isinstance(s, Skill)

    def test_unique_ids(self):
        ids = [s.id for s in default_skills()]
        assert len(ids) == len(set(ids))

    def test_each_has_knowledge(self):
        for s in default_skills():
            assert len(s.knowledge) > 0, f"Skill {s.id} has no knowledge"


class TestDefaultTeams:
    def test_returns_non_empty_list(self):
        teams = default_teams()
        assert len(teams) > 0

    def test_each_entry_is_persons_and_team(self):
        for persons, team in default_teams():
            assert isinstance(team, Team)
            assert all(isinstance(p, Person) for p in persons)

    def test_team_members_match_persons(self):
        for persons, team in default_teams():
            person_ids = {p.id for p in persons}
            assert set(team.members) == person_ids

    def test_lead_is_a_member(self):
        for persons, team in default_teams():
            assert team.lead_id in team.members

    def test_unique_team_ids(self):
        ids = [t.id for _, t in default_teams()]
        assert len(ids) == len(set(ids))
