{
  description = "Update config.toml and config.schema.json from OpenAI Codex sources";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];

      forAllSystems = f:
        builtins.listToAttrs (map (system: {
          name = system;
          value = f system;
        }) systems);
    in
    {
      packages = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
          update-config = pkgs.writeShellApplication {
            name = "exe";
            runtimeInputs = with pkgs; [
              python3
            ];
            text = ''
              python3 ${./scripts/update-schema.py}
              python3 ${./scripts/update-config.py}
              python3 ${./scripts/generate-toml-from-json-schema.py}
            '';
          };
        in
        {
          default = update-config;
        });

      apps = forAllSystems (system: {
        default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/exe";
        };
      });
    };
}
