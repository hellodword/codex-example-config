{
  description = "Update config.toml from the OpenAI Codex config sample";

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
              bash
              coreutils
              curl
              gnugrep
              htmlq
              python3
            ];
            text = ''
              bash ${./scripts/update-config.sh}
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
