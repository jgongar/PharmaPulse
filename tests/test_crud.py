"""Tests for CRUD operations."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend import crud, schemas


class TestAssetCRUD:
    def test_create_asset(self, db_session):
        data = schemas.AssetCreate(
            name="TestDrug", therapeutic_area="Oncology",
            indication="NSCLC", molecule_type="Small Molecule",
            current_phase="P1", is_internal=True,
        )
        asset = crud.create_asset(db_session, data)
        assert asset.id is not None
        assert asset.name == "TestDrug"

    def test_get_asset(self, db_session, sample_asset):
        fetched = crud.get_asset(db_session, sample_asset.id)
        assert fetched is not None
        assert fetched.name == sample_asset.name

    def test_get_nonexistent_asset(self, db_session):
        assert crud.get_asset(db_session, 9999) is None

    def test_update_asset(self, db_session, sample_asset):
        data = schemas.AssetUpdate(name="UpdatedDrug")
        updated = crud.update_asset(db_session, sample_asset.id, data)
        assert updated.name == "UpdatedDrug"

    def test_delete_asset(self, db_session, sample_asset):
        assert crud.delete_asset(db_session, sample_asset.id) is True
        assert crud.get_asset(db_session, sample_asset.id) is None

    def test_list_assets(self, db_session, sample_asset):
        assets = crud.get_assets(db_session)
        assert len(assets) >= 1


class TestSnapshotCRUD:
    def test_create_snapshot(self, db_session, sample_asset):
        data = schemas.SnapshotCreate(
            asset_id=sample_asset.id,
            label="Test Snapshot",
            phase_inputs=[
                schemas.PhaseInputSchema(
                    phase_name="P1", probability_of_success=0.6,
                    duration_years=2, start_year=2025,
                ),
            ],
            rd_costs=[
                schemas.RDCostSchema(year=2025, cost_usd_m=10.0),
            ],
        )
        snap = crud.create_snapshot(db_session, data)
        assert snap.id is not None
        assert snap.version == 1
        assert len(snap.phase_inputs) == 1
        assert len(snap.rd_costs) == 1

    def test_auto_version_increment(self, db_session, sample_asset):
        data1 = schemas.SnapshotCreate(asset_id=sample_asset.id, label="v1")
        snap1 = crud.create_snapshot(db_session, data1)
        assert snap1.version == 1

        data2 = schemas.SnapshotCreate(asset_id=sample_asset.id, label="v2")
        snap2 = crud.create_snapshot(db_session, data2)
        assert snap2.version == 2

    def test_update_snapshot_replaces_children(self, db_session, sample_asset):
        data = schemas.SnapshotCreate(
            asset_id=sample_asset.id,
            phase_inputs=[
                schemas.PhaseInputSchema(phase_name="P1", probability_of_success=0.5,
                                          duration_years=2, start_year=2025),
            ],
        )
        snap = crud.create_snapshot(db_session, data)

        update = schemas.SnapshotUpdate(
            phase_inputs=[
                schemas.PhaseInputSchema(phase_name="P1", probability_of_success=0.7,
                                          duration_years=2, start_year=2025),
                schemas.PhaseInputSchema(phase_name="P2", probability_of_success=0.4,
                                          duration_years=3, start_year=2027),
            ],
        )
        updated = crud.update_snapshot(db_session, snap.id, update)
        assert len(updated.phase_inputs) == 2
        assert updated.phase_inputs[0].probability_of_success == 0.7

    def test_delete_snapshot(self, db_session, sample_snapshot):
        assert crud.delete_snapshot(db_session, sample_snapshot.id) is True
        assert crud.get_snapshot(db_session, sample_snapshot.id) is None

    def test_get_snapshots_for_asset(self, db_session, sample_snapshot):
        snaps = crud.get_snapshots_for_asset(db_session, sample_snapshot.asset_id)
        assert len(snaps) >= 1


class TestPortfolioCRUD:
    def test_create_portfolio(self, db_session, sample_snapshot):
        data = schemas.PortfolioCreate(
            name="Test Portfolio",
            description="For testing",
            snapshot_ids=[sample_snapshot.id],
        )
        pf = crud.create_portfolio(db_session, data)
        assert pf.id is not None
        assert pf.name == "Test Portfolio"
        assert len(pf.members) == 1

    def test_delete_portfolio(self, db_session, sample_snapshot):
        data = schemas.PortfolioCreate(name="ToDelete", snapshot_ids=[sample_snapshot.id])
        pf = crud.create_portfolio(db_session, data)
        assert crud.delete_portfolio(db_session, pf.id) is True
        assert crud.get_portfolio(db_session, pf.id) is None
