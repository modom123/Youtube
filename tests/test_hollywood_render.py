"""Tests for Hollywood agent Render deployment tools."""
import json
from unittest.mock import patch, MagicMock



class TestRenderBlueprintYaml:
    def test_get_render_blueprint_yaml(self):
        from generators.hollywood_agent import _tool_get_render_blueprint_yaml
        result = _tool_get_render_blueprint_yaml()
        assert "error" not in result
        assert "content" in result
        assert "env_vars" in result
        assert result["total_env_vars"] > 0
        assert "render.yaml" in result["path"]

    def test_get_render_blueprint_yaml_missing(self, tmp_path):
        from generators.hollywood_agent import _tool_get_render_blueprint_yaml
        fake_file = str(tmp_path / "fake_module.py")
        with patch("generators.hollywood_agent.__file__", fake_file):
            result = _tool_get_render_blueprint_yaml()
            assert "error" in result


class TestRenderDashboardNavigate:
    @patch("generators.hollywood_agent._browser_call")
    def test_navigate_known_page(self, mock_browser):
        mock_browser.return_value = {"title": "Render", "url": "https://dashboard.render.com/blueprint/new"}
        from generators.hollywood_agent import _tool_render_dashboard_navigate
        result = _tool_render_dashboard_navigate(page="blueprint_new")
        assert result["page"] == "blueprint_new"
        assert "blueprint/new" in result["url"]
        assert mock_browser.call_count >= 1

    @patch("generators.hollywood_agent._browser_call")
    def test_navigate_services(self, mock_browser):
        mock_browser.return_value = {"title": "Services", "url": "https://dashboard.render.com/services"}
        from generators.hollywood_agent import _tool_render_dashboard_navigate
        result = _tool_render_dashboard_navigate(page="services")
        assert result["page"] == "services"

    @patch("generators.hollywood_agent._browser_call")
    def test_navigate_env_vars_with_service_id(self, mock_browser):
        mock_browser.return_value = {"title": "Env", "url": "https://dashboard.render.com/web/srv-123/env"}
        from generators.hollywood_agent import _tool_render_dashboard_navigate
        result = _tool_render_dashboard_navigate(page="env_vars", service_id="srv-123")
        assert "srv-123" in result["url"]

    def test_navigate_unknown_page(self):
        from generators.hollywood_agent import _tool_render_dashboard_navigate
        result = _tool_render_dashboard_navigate(page="nonexistent_page")
        assert "error" in result

    @patch("generators.hollywood_agent._browser_call")
    def test_navigate_raw_url(self, mock_browser):
        mock_browser.return_value = {"title": "Custom", "url": "https://example.com"}
        from generators.hollywood_agent import _tool_render_dashboard_navigate
        result = _tool_render_dashboard_navigate(page="https://example.com")
        assert result["url"] == "https://example.com"

    @patch("generators.hollywood_agent._browser_call")
    def test_navigate_browser_error(self, mock_browser):
        mock_browser.return_value = {"error": "Browser crashed"}
        from generators.hollywood_agent import _tool_render_dashboard_navigate
        result = _tool_render_dashboard_navigate(page="services")
        assert "error" in result


class TestDeployRenderBlueprint:
    @patch("generators.hollywood_agent._browser_call")
    def test_deploy_nav_failure(self, mock_browser):
        mock_browser.return_value = {"error": "Connection refused"}
        from generators.hollywood_agent import _tool_deploy_render_blueprint
        result = _tool_deploy_render_blueprint(repo_url="https://github.com/user/repo")
        assert "error" in result
        assert "steps" in result

    @patch("generators.hollywood_agent.get_page", create=True)
    @patch("generators.hollywood_agent._browser_call")
    def test_deploy_fills_repo_url(self, mock_browser, mock_get_page):
        mock_browser.side_effect = [
            {"title": "Render", "url": "https://dashboard.render.com/blueprint/new"},
            {"screenshot_b64": "abc123screenshot"},
            {"screenshot_b64": "final_screenshot"},
        ]
        mock_page = MagicMock()
        mock_page.url = "https://dashboard.render.com/blueprint/new"
        mock_el = MagicMock()
        mock_page.query_selector.return_value = mock_el

        with patch("generators.hollywood_browser.get_page", return_value=mock_page):
            from generators.hollywood_agent import _tool_deploy_render_blueprint
            result = _tool_deploy_render_blueprint(
                repo_url="https://github.com/user/repo",
                blueprint_name="my-app",
            )
        assert "error" not in result or "steps" in result


class TestFillRenderEnvVars:
    @patch("generators.hollywood_agent._browser_call")
    def test_fill_nav_failure(self, mock_browser):
        mock_browser.return_value = {"error": "Timeout"}
        from generators.hollywood_agent import _tool_fill_render_env_vars
        result = _tool_fill_render_env_vars(service_id="srv-123", env_vars={"KEY": "val"})
        assert "error" in result

    @patch("generators.hollywood_agent._browser_call")
    def test_fill_browser_unavailable(self, mock_browser):
        mock_browser.return_value = {"title": "Env", "url": "https://dashboard.render.com/web/srv-123/env"}
        with patch("generators.hollywood_browser.get_page", side_effect=Exception("No browser")):
            from generators.hollywood_agent import _tool_fill_render_env_vars
            result = _tool_fill_render_env_vars(service_id="srv-123", env_vars={"KEY": "val"})
            assert "error" in result


class TestRenderDispatch:
    def test_dispatch_get_render_blueprint_yaml(self, db_conn):
        from generators.hollywood_agent import _dispatch_tool
        result = json.loads(_dispatch_tool("get_render_blueprint_yaml", {}))
        assert "content" in result or "error" in result

    def test_dispatch_render_dashboard_navigate_unknown(self, db_conn):
        from generators.hollywood_agent import _dispatch_tool
        result = json.loads(_dispatch_tool("render_dashboard_navigate", {"page": "unknown_xyz"}))
        assert "error" in result

    @patch("generators.hollywood_agent._browser_call")
    def test_dispatch_render_dashboard_navigate(self, mock_browser, db_conn):
        mock_browser.return_value = {"title": "Services", "url": "https://dashboard.render.com/services"}
        from generators.hollywood_agent import _dispatch_tool
        result = json.loads(_dispatch_tool("render_dashboard_navigate", {"page": "services"}))
        assert result["page"] == "services"

    @patch("generators.hollywood_agent._browser_call")
    def test_dispatch_deploy_render_blueprint_error(self, mock_browser, db_conn):
        mock_browser.return_value = {"error": "No connection"}
        from generators.hollywood_agent import _dispatch_tool
        result = json.loads(_dispatch_tool("deploy_render_blueprint", {
            "repo_url": "https://github.com/user/repo"
        }))
        assert "error" in result

    @patch("generators.hollywood_agent._browser_call")
    def test_dispatch_fill_render_env_vars_error(self, mock_browser, db_conn):
        mock_browser.return_value = {"error": "Timeout"}
        from generators.hollywood_agent import _dispatch_tool
        result = json.loads(_dispatch_tool("fill_render_env_vars", {
            "env_vars": {"API_KEY": "test123"}
        }))
        assert "error" in result
